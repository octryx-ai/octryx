"""``octryx-claude device run``: the device background service.

One instance per state dir (an exclusive lock on ``device.lock``), a rotating log in ``logs/device.log``, the
outbound channel (``device_channel``) and the job manager (``device_jobs``). SIGTERM/SIGINT stop it cleanly:
running turns are interrupted first.

Self-update: the start itself goes through ``self_update.on_start`` like every launcher command. While it
runs, ``update_watch`` checks every ``UPDATE_INTERVAL_SECONDS`` whether no job is running; then it builds and
activates a newly served version, waits until no job runs, stops the service cleanly and re-executes
``device run`` through the shim (same process, so launchd, systemd and the WSL logon task need no restart policy;
the logon task has none for a process that exits). Should the re-exec fail, the exit code
``EXIT_RESTART_FOR_UPDATE`` (non-zero) makes launchd (``KeepAlive.SuccessfulExit=false``) and systemd
(``Restart=on-failure``) start it again on the new version. A running job is never interrupted for an update.
"""

from __future__ import annotations

import asyncio
import contextlib
import fcntl
import logging
import os
import signal
import sys
from collections.abc import Callable, Iterator
from logging.handlers import RotatingFileHandler
from typing import Any

from octryx_claude import self_update_state

from . import __version__, codex_seat, device_service, device_state, self_update, tools
from .device_channel_auth import channel_token, revocation_check
from .device_folder_access import folder_watch
from .device_watches import (
    health_watch,
    local_model_watch,
    update_watch,
)
from .install_layout import installed_version
from .profile_choice import seat_logged_in
from .state import LocalState

LOG_MAX_BYTES = 1024 * 1024
LOG_BACKUPS = 3
# Nobody waits on the background check, so a slow platform or tunnel is not "offline".
SERVICE_UPDATE_TIMEOUT_SECONDS = 15.0
EXIT_RESTART_FOR_UPDATE = 75  # EX_TEMPFAIL
SERVICE_ARGV = ("device", "run")


class AlreadyRunningError(Exception):
    pass


@contextlib.contextmanager
def single_instance(state: LocalState) -> Iterator[None]:
    fd = os.open(str(state.ensure().root / device_state.LOCK_FILE), os.O_RDWR | os.O_CREAT, 0o600)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise AlreadyRunningError from exc
        yield
    finally:
        with contextlib.suppress(OSError):
            fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def configure_logging(state: LocalState) -> None:
    handler = RotatingFileHandler(device_state.log_path(state), maxBytes=LOG_MAX_BYTES, backupCount=LOG_BACKUPS)
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger = logging.getLogger("octryx_claude.device")
    logger.handlers[:] = [handler]
    logger.setLevel(logging.INFO)
    logger.propagate = False


def device_report(state: LocalState) -> dict[str, Any]:
    """What the device says about itself in ``hello`` and ``state`` (the platform may only narrow folders)."""
    device = device_state.load_device(state)
    seat = seat_logged_in(state)
    return {
        "folders": list(device.get("folders") or []),
        "profiles_available": ["governed", "seat"] if seat else ["governed"],
        "max_parallel_jobs": int(device.get("max_parallel_jobs") or device_state.DEFAULT_PARALLEL_JOBS),
        "paused": bool(device.get("paused")),
        "seat_login": seat,
        # The Codex seat (the person's own ChatGPT login): ``codex login status``'s exit code, never the login itself.
        "codex_seat_login": codex_seat.reported_login(state.root),
        "client_version": installed_version() or __version__,  # the build (``0.2.0+<hash>``), not the series
        "service_kind": str(device.get("service_kind") or "foreground"),
        "live": bool(device.get("live")),
        # The pinned tools this device has (the launcher brings everything the platform needs).
        "tools": tools.reported(state.root),
    }


def _check_update(state: LocalState) -> self_update.Updated | None:
    logger = logging.getLogger("octryx_claude.device")
    return self_update.update_if_available(state, warn=logger.warning, timeout=SERVICE_UPDATE_TIMEOUT_SECONDS)



def _confirm_healthy(state: LocalState) -> None:
    layout = self_update.detect_layout(state)
    if layout is not None:
        self_update_state.confirm_healthy(layout, installed_version())


def _start_attempt(state: LocalState) -> self_update.Updated | None:
    """A start on a freshly activated version that keeps failing goes back to the previous version."""
    try:
        layout = self_update.detect_layout(state)
        running = installed_version()
        previous = self_update_state.start_attempt(state, layout, running) if layout is not None else ""
    except Exception:  # noqa: BLE001 - the rollback guard never stops the service from starting
        return None
    return self_update.Updated(previous=running, version=previous, layout=layout) if previous else None


async def serve(state: LocalState, stop: asyncio.Event, *,
                check_update: Callable[[], self_update.Updated | None] | None = None,
                confirm_healthy: Callable[[], None] | None = None) -> self_update.Updated | None:
    """Runs the service until ``stop``; returns the activated update when it stopped for one."""
    from .device_channel import ChannelClient
    from .device_jobs import JobManager
    from .live_bridge import LiveBridge

    manager = JobManager(state)
    live = LiveBridge(state)

    async def on_message(message_type: str, body: dict[str, Any]) -> None:
        if message_type.startswith("live_") or message_type == "connected":
            await live.handle(message_type, body)
        if not message_type.startswith("live_"):
            await manager.handle(message_type, body)

    client = ChannelClient(state, token_provider=lambda force: channel_token(state, force),
                           report=lambda: device_report(state), on_message=on_message,
                           confirm_revoked=lambda: revocation_check(state),
                           recheck_revoked=lambda: revocation_check(state, recheck=True))
    manager.attach(client)
    live.attach(client)
    live_task = asyncio.create_task(live.run(stop))
    idle_task = asyncio.create_task(local_model_watch(manager, stop))
    watch = asyncio.create_task(update_watch(manager, stop, check=check_update or (lambda: _check_update(state))))
    folders = asyncio.create_task(folder_watch(state, stop))
    health = asyncio.create_task(health_watch(client, stop, confirm_healthy or (lambda: _confirm_healthy(state))))
    try:
        await client.run_forever(stop)
    finally:
        await manager.stop_all("service_stopped")
        await live.stop()
        await manager.stop_local_model()
        for task in (folders, health, live_task, idle_task):
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task
        if not watch.done():
            watch.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await watch
    return watch.result() if watch.done() and not watch.cancelled() and watch.exception() is None else None


def reconcile_service_unit(state: LocalState, *, manager: Any = None, env: dict[str, str] | None = None) -> str:
    """At every start: the installed unit becomes the definition this launcher writes (``device_service.reconcile``).
    Inside the LaunchAgent a replaced plist is loaded by a detached helper (``bootout`` + ``bootstrap``; this start
    runs no job yet). ``""`` (already current), ``replaced`` or ``reloading``."""
    device = device_state.load_device(state)
    kind = str(device.get("service_kind") or "")
    if kind not in ("launchd", "systemd"):
        return ""
    try:
        service = manager or device_service.manager_for(str(device.get("os") or ""))
        if not service.reconcile(device_service.service_shim(), device_state.log_path(state)):
            return ""
    except (device_service.ServiceError, OSError):
        return ""
    if kind == "launchd" and device_service.launched_by_launchd(env) and service.reload_detached():
        return "reloading"
    return "replaced"


# SIGHUP too: closing the screen session that runs the service sends it.
STOP_SIGNALS = (signal.SIGTERM, signal.SIGINT, signal.SIGHUP)


def on_stop_signal(logger: logging.Logger, stop: asyncio.Event, signum: int) -> None:
    """A stop by signal is logged, so a deliberate stop is never confused with a crash."""
    logger.warning("device service stopping: %s received", signal.Signals(signum).name)
    stop.set()


def run_logged(logger: logging.Logger, run: Callable[[], Any]) -> Any:
    """Every end of the service is in its log: an exception with its traceback (not only on stderr), and the regular
    end."""
    try:
        result = run()
    except BaseException:
        logger.exception("device service ended by an unhandled exception")
        raise
    logger.info("device service stopped")
    return result


def _ensure_tools(state: LocalState, logger: logging.Logger) -> None:
    """The launcher's pinned tools after an install or update, in the background (never blocks the start)."""
    import threading  # noqa: PLC0415

    def work() -> None:
        try:
            for problem in tools.ensure(state.root):
                logger.warning("tools: %s", problem)
        except Exception:  # noqa: BLE001 - a missing tool is said; the service runs on
            logger.warning("tools: could not check the launcher's tools", exc_info=True)

    threading.Thread(target=work, name="octryx-tools", daemon=True).start()


def run_service(state: LocalState) -> int:
    device = device_state.load_device(state)
    if not device.get("device_id"):
        sys.stderr.write("octryx-claude: this device is not enabled (run: octryx-claude device enable)\n")
        return 2
    try:
        with single_instance(state):
            configure_logging(state)
            logger = logging.getLogger("octryx_claude.device")
            logger.info("device service starting (%s)", installed_version() or __version__)
            try:  # a previous instance's hands-on app left running blocks every later pass on its port
                from .hands_on_app import reap_all  # noqa: PLC0415

                if ended := reap_all(state.root):
                    logger.info("hands_on: ended %d serve group(s) of the previous instance", ended)
            except Exception:  # noqa: BLE001 - never blocks the service's start
                logger.warning("hands_on: could not check for serve groups left running", exc_info=True)
            tools.use_own_browsers(state.root)  # hands-on: Playwright's Chromium from the launcher's folder
            _ensure_tools(state, logger)
            if rollback := _start_attempt(state):
                logger.warning("update_rolled_back: %s did not start healthy %d times; back to %s",
                               rollback.previous, self_update_state.MAX_START_ATTEMPTS, rollback.version)
                updated: self_update.Updated | None = rollback
            else:
                updated = None
            if updated is None and (reconciled := reconcile_service_unit(state)):
                logger.info("service unit reconciled: %s", reconciled)

            async def main() -> self_update.Updated | None:
                stop = asyncio.Event()
                loop = asyncio.get_running_loop()
                for signum in STOP_SIGNALS:
                    with contextlib.suppress(NotImplementedError, ValueError):
                        loop.add_signal_handler(signum, on_stop_signal, logger, stop, signum)
                return await serve(state, stop)

            if updated is None:
                updated = run_logged(logger, lambda: asyncio.run(main()))
    except AlreadyRunningError:
        sys.stderr.write("octryx-claude: the device service is already running\n")
        return 1
    if updated is None:
        return 0
    # The lock is released: the re-executed service takes it again on the new version.
    self_update.restart(SERVICE_ARGV, updated, sys.stderr)
    return EXIT_RESTART_FOR_UPDATE


__all__ = [
    "device_report",
    "reconcile_service_unit",
    "run_service",
    "serve",
    "single_instance",
]
