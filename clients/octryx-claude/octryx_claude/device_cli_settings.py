"""The device's local settings: ``pause``/``resume``, ``folders``, ``parallel``, ``context``, ``live`` and ``logs``."""

from __future__ import annotations

import argparse
import sys
import time
from collections.abc import Callable
from pathlib import Path

from . import device_state, live_progress
from .device_cli_common import _ask, _fail, _update
from .device_cli_enable import Probe, _local_blocked, _service_blocked
from .state import LocalState

FOLLOW_INTERVAL = 1.0


def run_pause(state: LocalState, paused: bool) -> int:
    if _update(state, paused=paused) is None:
        return _fail("this device is not enabled")
    print("Paused: new jobs are rejected and running jobs stop." if paused else "Resumed: jobs are accepted again.")
    return 0


def run_context(args: argparse.Namespace, state: LocalState) -> int:
    device = device_state.load_device(state)
    if args.tokens is None:
        print(f"Mac turns compact at {device_state.context_window(device):,} tokens.")
        return 0
    if not device_state.MIN_CONTEXT_WINDOW <= args.tokens <= device_state.MAX_CONTEXT_WINDOW:
        return _fail("denied: between 100000 and 300000 tokens")
    if _update(state, context_window=args.tokens) is None:
        return _fail("this device is not enabled")
    print(f"Mac turns now compact at {args.tokens:,} tokens.")
    return 0


def run_live(args: argparse.Namespace, state: LocalState) -> int:
    device = device_state.load_device(state)
    if not device.get("device_id"):
        return _fail("this device is not enabled")
    if args.live_action == "status":
        print("live sessions: " + ("on" if device.get("live") else "off"))
        print("live progress: " + ("on" if live_progress.enabled(state) else "off"))
        return 0
    if args.live_action == "progress":
        if args.progress_action == "status":
            print("live progress: " + ("on" if live_progress.enabled(state) else "off"))
            return 0
        config = state.config()
        config["live_progress"] = args.progress_action == "on"
        state.ensure().write_config(config)
        print("Live progress on: your phone sees what the listed sessions are doing (narration, tool calls, whether "
              "they worked; never thinking or file contents)." if args.progress_action == "on"
              else "Live progress off: your phone sees only the sessions' answers.")
        return 0
    _update(state, live=args.live_action == "on")
    print("Live sessions on: your phone sees the Claude Code sessions running here and can message them."
          if args.live_action == "on" else "Live sessions off: your phone no longer sees or reaches them.")
    return 0


def run_folders(args: argparse.Namespace, state: LocalState, *, ask: Callable[[str], str] = _ask,
                probe: Probe | None = None) -> int:
    device = device_state.load_device(state)
    if not device.get("device_id"):
        return _fail("this device is not enabled")
    folders = list(device.get("folders") or [])
    if args.folder_action == "list":
        print("\n".join(folders) if folders else "(no folder allowed)")
        return 0
    if not args.path:
        return _fail(f"folders {args.folder_action} needs a PATH")
    if args.folder_action == "remove":
        target = str(Path(args.path).expanduser().resolve())
        remaining = [folder for folder in folders if folder not in (args.path, target)]
        if remaining == folders:
            return _fail("denied: folder_not_allowlisted")
        _update(state, folders=remaining)
        print(f"Removed {target}.")
        return 0
    try:
        folder = device_state.local_folder(args.path)
    except device_state.DeviceStateError as exc:
        return _fail(f"denied: {exc.code}")
    if folder in folders:
        print(f"{folder} is already allowed.")
        return 0
    os_name = str(device.get("os") or "")
    if warning := device_state.protected_folder_warning(folder, os_name=os_name):
        sys.stderr.write(f"octryx-claude: {warning}\n")
    if note := device_state.checkout_note(folder):
        sys.stderr.write(f"octryx-claude: {note}\n")
    if refusal := _local_blocked([folder], os_name):
        return _fail(refusal)
    # Widening is only possible here, on the device, and only with a local confirmation.
    if not args.yes and ask(f"Allow jobs from the platform to run in {folder}? [y/N] ").strip().lower() != "y":
        return _fail("not added")
    refusal, answered = _service_blocked(state, [folder], os_name, probe)
    if refusal:
        return _fail(f"denied: {refusal}")
    _update(state, folders=[*folders, folder])
    print(f"Added {folder}." + ("" if answered else " The service checks its access before every job."))
    return 0


def run_parallel(args: argparse.Namespace, state: LocalState) -> int:
    try:
        count = device_state.parallel_jobs(args.count)
    except device_state.DeviceStateError as exc:
        return _fail(f"denied: {exc.code} (1-8)")
    if _update(state, max_parallel_jobs=count) is None:
        return _fail("this device is not enabled")
    print(f"Up to {count} chats run here at the same time.")
    return 0


def run_logs(args: argparse.Namespace, state: LocalState, *, follow_until: Callable[[], bool] | None = None) -> int:
    path = device_state.log_path(state)
    if not path.exists():
        print("(no log yet)")
        return 0
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    for line in lines[-max(1, args.lines):]:
        print(line)
    if not args.follow:
        return 0
    position = path.stat().st_size
    stop = follow_until or (lambda: False)
    try:
        while not stop():
            time.sleep(FOLLOW_INTERVAL)
            size = path.stat().st_size if path.exists() else 0
            if size < position:  # rotated
                position = 0
            if size > position:
                with path.open("r", encoding="utf-8", errors="replace") as handle:
                    handle.seek(position)
                    sys.stdout.write(handle.read())
                    sys.stdout.flush()
                position = size
    except KeyboardInterrupt:
        return 0
    return 0
