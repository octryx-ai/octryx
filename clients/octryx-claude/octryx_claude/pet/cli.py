"""The pet's commands: run the tray icon, start it at login, set its quiet hours and notifications.
Inside WSL2 there is no tray, so ``run`` and ``enable`` point at the native ``octryx-pet``."""

from __future__ import annotations

import argparse
import importlib.util
import logging
import os
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx

from . import api
from . import settings as pet_settings
from .account import Account
from .display import present

PET_EXTRA_HINT = ("octryx-claude: the pet needs pystray and Pillow in this installation "
                  "(pip install 'octryx-claude[pet]').\n")
WSL_HINT = ("octryx-claude: inside WSL there is no tray icon; on Windows the pet runs natively: "
            "octryx-pet enable (installed by install.ps1)")


def add_arguments(parser: argparse.ArgumentParser) -> None:
    actions = parser.add_subparsers(dest="pet_command", required=True)
    run = actions.add_parser("run", help="show the tray icon (the login item calls this)")
    run.add_argument("--workspace", default="", help="only this Workspace (id); default: all of yours")
    actions.add_parser("enable", help="show the tray icon now and at every login")
    actions.add_parser("disable", help="turn it off: stop it and do not start it at login any more")
    autostart = actions.add_parser("autostart", help="for the installers: on, unless you turned it off")
    autostart.add_argument("--restart", action="store_true", help="restart a running pet (a new version)")
    actions.add_parser("status", help="platform, autostart, settings and the current state")
    quiet = actions.add_parser("quiet", help="quiet hours in local time: HH:MM-HH:MM, on or off (default: none)")
    quiet.add_argument("value")
    notifications = actions.add_parser("notifications", help="notifications on or off (the icon always shows)")
    notifications.add_argument("value", choices=("on", "off"))


def add_parser(sub: argparse._SubParsersAction) -> None:
    add_arguments(sub.add_parser("pet", help="the Octryx tray icon: what needs you, at a glance"))


def _fail(message: str, code: int = 2) -> int:
    sys.stderr.write(f"octryx-claude: {message}\n")
    return code


def in_wsl(env: dict[str, str] | None = None, proc_version: Path = Path("/proc/version")) -> bool:
    source = os.environ if env is None else env
    if source.get("WSL_DISTRO_NAME"):
        return True
    try:
        return "microsoft" in proc_version.read_text(encoding="utf-8").lower()
    except OSError:
        return False


def _run(args: argparse.Namespace, account: Account) -> int:
    try:
        from .runner import Runner  # noqa: PLC0415
        from .service import instance_lock  # noqa: PLC0415
        from .tray import Tray  # noqa: PLC0415
    except ImportError:
        sys.stderr.write(PET_EXTRA_HINT)
        return 2
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    updated: list[str] = []
    with instance_lock(account.root) as alone:
        if not alone:
            logging.getLogger("octryx_claude.pet").info("another pet runs already; this one exits")
            return 0
        tray = Tray(lambda view: Runner(account, view, project_id=args.workspace))
        stop_updates = _start_windows_updates(account, tray, updated)
        try:
            tray.run()
        finally:
            stop_updates()
    if updated and not tray.turned_off:  # the lock is free again: the new version starts as at logon
        _restart_after_update(updated[0])
        return 0
    if tray.turned_off:  # "Turn off Octryx" in the menu: the same as `pet disable` (on macOS the bootout ends us)
        logging.getLogger("octryx_claude.pet").info("turned off from the menu")
        return _autostart("disable", account)
    return 0


def _start_windows_updates(account: Account, tray: Any, updated: list[str]) -> Callable[[], None]:
    if os.name != "nt":
        return lambda: None
    import threading  # noqa: PLC0415

    from .win_update import watch  # noqa: PLC0415

    stop = threading.Event()

    def handover(version: str) -> None:
        updated.append(version)
        tray.quit()  # ends tray.run(); the restart follows once the lock is released

    threading.Thread(target=watch, args=(account, stop, handover), name="octryx-pet-update", daemon=True).start()
    return stop.set


def _restart_after_update(version: str) -> None:
    from .service import default_spawn, run_command, windowless_python  # noqa: PLC0415

    logging.getLogger("octryx_claude.pet").info("restarting on %s", version)
    default_spawn(run_command(windowless_python()))


def _command(action: str) -> str:
    return f"octryx-pet {action}" if os.name == "nt" else f"octryx-claude pet {action}"


def _pet_extra_present() -> bool:
    return all(importlib.util.find_spec(name) is not None for name in ("pystray", "PIL"))


def _autostart_status(account: Account) -> str:
    if pet_settings.autostart_off(account.root):
        return f"off (turned off; turn on again: {_command('enable')})"
    if sys.platform == "darwin":
        agent = _launch_agent()
        return ("yes" if agent.installed() else "no") + (" (running)" if agent.installed() and agent.running() else "")
    if os.name == "nt":
        from .service import RunKey  # noqa: PLC0415

        return "yes" if RunKey().installed() else "no"
    return "not available here"


def _status(account: Account) -> int:
    current = pet_settings.load(account.root)
    hours = current.quiet_hours
    lines = [
        f"platform:       {account.base_url() or '(not configured)'}",
        f"notifications:  {'on' if current.notifications else 'off'}",
        f"quiet hours:    {hours.label() + (' (on)' if hours.enabled else ' (off)')}",
        f"start at login: {_autostart_status(account)}",
    ]
    with httpx.Client() as http:
        result = api.fetch(account, http=http)
    connection = {"signed_out": "signed_out", "ok": "ok"}.get(result.outcome, "offline")
    lines.append(f"state:          {present(result.pet, connection).header}"
                 + (f" ({result.reason})" if result.reason and result.outcome != "ok" else ""))
    print("\n".join(lines))
    return 0


def _quiet(value: str, account: Account) -> int:
    current = pet_settings.load(account.root)
    if value in ("on", "off"):
        updated = pet_settings.with_quiet_hours(current, enabled=value == "on")
    else:
        window = pet_settings.parse_window(value)
        if window is None:
            return _fail("quiet hours are HH:MM-HH:MM (for example 19:00-08:00), on or off")
        updated = pet_settings.with_quiet_hours(current, enabled=True, window=window)
    account.root.mkdir(parents=True, exist_ok=True)
    pet_settings.save(account.root, updated)
    hours = updated.quiet_hours
    print(f"quiet hours: {hours.label()} ({'on' if hours.enabled else 'off'}, local time)")
    return 0


def _launch_agent():  # noqa: ANN202 - the macOS LaunchAgent
    from octryx_claude.device_service_units import instance_label  # noqa: PLC0415

    from .service import LAUNCHD_LABEL, LaunchAgent  # noqa: PLC0415

    return LaunchAgent(home=Path.home(), uid=os.getuid(), label=instance_label(LAUNCHD_LABEL))


def _autostart(command: str, account: Account, *, restart: bool = True) -> int:
    from .service import PetServiceError, RunKey  # noqa: PLC0415

    if sys.platform != "darwin" and os.name != "nt":
        return _fail("start at login is available on macOS and Windows")
    if command == "autostart" and pet_settings.autostart_off(account.root):
        print(f"octryx-claude: the pet stays off, as you set it (turn it on: {_command('enable')})")
        return 0
    turn_on = command in ("enable", "autostart")
    if turn_on and not _pet_extra_present():
        command, turn_on = "remove", False
    started = True
    try:
        if command == "enable":
            pet_settings.set_autostart_off(account.root, False)
        elif command == "disable":
            pet_settings.set_autostart_off(account.root, True)
        if sys.platform == "darwin":
            from ..device_service import service_shim  # noqa: PLC0415

            if turn_on:
                account.root.mkdir(parents=True, exist_ok=True)
                started = _launch_agent().install([str(service_shim())], account.root / "pet.log", restart=restart)
            else:
                _launch_agent().remove()
        elif turn_on:
            RunKey().install()
        else:
            RunKey().remove()
    except OSError:
        return _fail("autostart failed (state_unwritable)")
    except PetServiceError as exc:
        return _fail(f"autostart failed ({exc.code})")
    if command == "remove":
        sys.stderr.write(PET_EXTRA_HINT)
        return 2
    if turn_on:
        print(f"octryx-claude: the pet {'runs now' if started else 'runs'} and starts at every login "
              f"(turn it off: {_command('disable')}, or \"Turn off Octryx\" in its menu)")
    else:
        print(f"octryx-claude: the pet is off and no longer starts at login (turn it on again: {_command('enable')})")
    return 0


def run_pet_command(args: argparse.Namespace, account: Account) -> int:
    command = args.pet_command
    if command in ("run", "enable", "autostart") and in_wsl():
        return _fail(WSL_HINT.removeprefix("octryx-claude: "))
    if command == "run":
        return _run(args, account)
    if command == "status":
        return _status(account)
    if command == "quiet":
        return _quiet(args.value, account)
    if command == "notifications":
        current = pet_settings.load(account.root)
        account.root.mkdir(parents=True, exist_ok=True)
        pet_settings.save(account.root, pet_settings.PetSettings(
            notifications=args.value == "on", quiet_hours=current.quiet_hours))
        print(f"notifications: {args.value}")
        return 0
    return _autostart(command, account, restart=getattr(args, "restart", True) or command != "autostart")


def main(argv: list[str] | None = None) -> int:
    """``python -m octryx_claude.pet`` (the native Windows pet; ``octryx-pet.cmd`` calls it)."""
    from .account import default_account  # noqa: PLC0415

    parser = argparse.ArgumentParser(prog="octryx-pet", description="the Octryx tray icon: what needs you")
    add_arguments(parser)
    return run_pet_command(parser.parse_args(argv), default_account())


__all__ = ["add_parser", "main", "run_pet_command"]
