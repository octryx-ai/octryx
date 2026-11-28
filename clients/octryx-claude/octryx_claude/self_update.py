"""Self-update of an installed octryx-claude on start."""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
import time
from collections.abc import Callable, MutableMapping, Sequence
from pathlib import Path
from typing import TextIO

import httpx

from . import update_check
from .install_layout import installed_version
from .self_update_commands import (
    Runner,
    _reports,
    _run,
    build_commands,
    default_runner,
    download,
    pet_autostart_command,
    pet_command,
)
from .self_update_layout import (
    Layout,
    Updated,
    UpdateError,
    prune,
    switch,
)
from .self_update_lock import (
    _update_lock,
)
from .self_update_state import (
    CACHED_FAILURE,
    CHECK_TIMEOUT_SECONDS,
    _cached_release,
    _held_back,
    _recently_failed,
    _remember,
    _remember_failure,
    mark_pending,
)
from .state import LocalState

AUTO_UPDATE_ENV = "OCTRYX_CLAUDE_AUTO_UPDATE"
REEXEC_GUARD_ENV = "OCTRYX_CLAUDE_UPDATED_TO"
HEALTHY_AFTER_SECONDS = 120.0
# The Octryx pet (``octryx-claude[pet]``): macOS only for now; ``<state>/no-pet`` is install.sh's recorded opt-out.
NO_PET_FILE = "no-pet"
_OFF = ("0", "false", "no", "off")

Warn = Callable[[str], None]


def enabled(env: MutableMapping[str, str] | None = None) -> bool:
    return (os.environ if env is None else env).get(AUTO_UPDATE_ENV, "").strip().lower() not in _OFF


def detect_layout(state: LocalState, *, prefix: str | None = None, home: Path | None = None) -> Layout | None:
    layout = Layout(state.root, home or Path.home())
    if not layout.current.is_symlink():
        return None
    try:
        running = Path(prefix or sys.prefix).resolve()
        venvs = layout.venvs.resolve()
    except OSError:
        return None
    if running.parent != venvs:
        return None
    _refuse_claude_path(layout.venvs, layout.home)
    return layout


def _refuse_claude_path(path: Path, home: Path) -> None:
    try:
        relative = path.resolve().relative_to(home.resolve())
    except ValueError:
        return
    if relative.parts and relative.parts[0].startswith(".claude"):
        raise UpdateError("refused_claude_path")


# --- the served release (cached) --------------------------------------------------------------------------------


# --- start health and rollback ------------------------------------------------------------------------------------


# --- build, verify, switch ----------------------------------------------------------------------------------------


def wants_pet(root: Path, platform: str | None = None) -> bool:
    return (platform or sys.platform) == "darwin" and not (root / NO_PET_FILE).exists()


def build(layout: Layout, release: update_check.Release, http: httpx.Client, base_url: str, *,
          runner: Runner = default_runner, env: MutableMapping[str, str] | None = None) -> Path:
    env = os.environ if env is None else env
    venv = layout.venvs / release.version
    if _reports(runner, venv, release.version):
        return venv
    with tempfile.TemporaryDirectory(prefix="octryx-update.") as tmp:
        wheel = Path(tmp) / release.filename
        download(http, base_url, release, wheel)
        shutil.rmtree(venv, ignore_errors=True)
        for argv in build_commands(venv, wheel, env):
            done = _run(runner, argv)
            if done is None or done.returncode != 0:
                shutil.rmtree(venv, ignore_errors=True)
                raise UpdateError("build_failed")
        if wants_pet(layout.root):
            _run(runner, pet_command(venv, wheel, env))  # never fatal: the launcher works without the pet
    if not _reports(runner, venv, release.version):
        shutil.rmtree(venv, ignore_errors=True)
        raise UpdateError("build_unverified")
    return venv


# --- the whole step -----------------------------------------------------------------------------------------------


def update_if_available(state: LocalState | None = None, *, warn: Warn, http: httpx.Client | None = None,
                        runner: Runner = default_runner, env: MutableMapping[str, str] | None = None,
                        now: float | None = None, installed: str | None = None, prefix: str | None = None,
                        home: Path | None = None, timeout: float = CHECK_TIMEOUT_SECONDS) -> Updated | None:
    env = os.environ if env is None else env
    mine = installed_version() if installed is None else installed
    if not mine or not enabled(env):
        return None
    state = state or LocalState()
    base_url = str(state.config().get("base_url") or "").rstrip("/")
    if not base_url:
        return None
    try:
        layout = detect_layout(state, prefix=prefix, home=home)
    except UpdateError as exc:
        warn(f"octryx-claude: update skipped ({exc.code})")
        return None
    if layout is None:
        return None
    moment = time.time() if now is None else now
    client = http or httpx.Client()
    try:
        try:
            release = _cached_release(state, base_url, moment, client, timeout)
        except update_check.ReleaseUnavailableError as exc:
            if exc.code != CACHED_FAILURE:
                warn(f"octryx-claude: update check failed ({exc.code}); running {mine}")
            return None
        if release.version == mine or _recently_failed(state, release.version, moment) \
                or _held_back(state, release.version, moment):
            return None
        with _update_lock(layout) as locked:
            if not locked:
                return None  # another start is updating right now; this one runs the installed version
            try:
                if layout.active() != release.version:
                    venv = build(layout, release, client, base_url, runner=runner, env=env)
                    previous = switch(layout, release.version)
                    _remember(state, left_version=mine, left_at=moment)
                    mark_pending(layout, release.version, mine, moment)
                    if wants_pet(layout.root):
                        _run(runner, pet_autostart_command(venv))  # never fatal, like the extra itself
                else:
                    previous = mine  # another process switched already; only the re-exec is left
                prune(layout, keep=(release.version, previous, mine))
            except (UpdateError, OSError) as exc:
                code = exc.code if isinstance(exc, UpdateError) else "switch_failed"
                _remember_failure(state, release.version, moment)
                warn(f"octryx-claude: update to {release.version} failed ({code}); running {mine}")
                return None
        return Updated(previous=mine, version=release.version, layout=layout)
    finally:
        if http is None:
            client.close()


def restart(argv: Sequence[str], updated: Updated, err: TextIO, *, env: MutableMapping[str, str] | None = None,
            execv: Callable[[str, list[str]], object] | None = None) -> None:
    env = os.environ if env is None else env
    shim = str(updated.layout.shim)
    err.write(f"octryx-claude updated {updated.previous} -> {updated.version}\n")
    err.flush()
    env[REEXEC_GUARD_ENV] = updated.version
    try:
        (execv or os.execv)(shim, [shim, *argv])
    except OSError:
        env.pop(REEXEC_GUARD_ENV, None)
        err.write(f"octryx-claude: could not restart on {updated.version}; this run stays on {updated.previous}\n")
        err.flush()


def on_start(argv: Sequence[str], err: TextIO, *, env: MutableMapping[str, str] | None = None,
             **kwargs) -> None:
    env = os.environ if env is None else env
    try:
        if env.pop(REEXEC_GUARD_ENV, None):
            return  # the process this step just started: no second check, no loop
        if not enabled(env):
            update_check.notify(err)
            return

        def warn(line: str) -> None:
            err.write(line + "\n")
            err.flush()

        updated = update_if_available(warn=warn, env=env, **kwargs)
        if updated is not None:
            restart(argv, updated, err, env=env)
    except Exception:  # noqa: BLE001 - the update is best effort and never stops a command
        return


__all__ = [
    "AUTO_UPDATE_ENV",
    "REEXEC_GUARD_ENV",
    "build",
    "detect_layout",
    "enabled",
    "on_start",
    "restart",
    "update_if_available",
]
