"""The audit spool of a session that decides on the device (``local_decisions``): every local denial and every
tool's execution evidence, uploaded in batches. Stdlib only."""

from __future__ import annotations

import contextlib
import json
import os
import time
from pathlib import Path
from typing import Any

SPOOL_FILE = "audit-spool.jsonl"
SENDING_PREFIX = "audit-sending-"
LOCK_FILE = "audit.lock"
MAX_EVENTS_PER_BATCH = 200
MAX_BATCH_BYTES = 1_500_000


def _slim(hook_input: dict[str, Any]) -> dict[str, Any]:
    keep = ("hook_event_name", "tool_name", "tool_use_id", "tool_input", "cwd", "agent_id", "agent_type",
            "permission_mode", "workflow_run_facts")
    return {key: hook_input[key] for key in keep if key in hook_input}


# One write per event, so parallel subagents' hooks never interleave.
def spool(folder: Path, event: str, hook_input: dict[str, Any], **extra: Any) -> None:
    line = json.dumps({"event": event, "at": time.time(), "hook_input": _slim(hook_input), **extra},
                      ensure_ascii=False, default=str) + "\n"
    descriptor = os.open(str(folder / SPOOL_FILE), os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    try:
        os.write(descriptor, line.encode("utf-8"))
    finally:
        os.close(descriptor)


def _batches(events: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    batches: list[list[dict[str, Any]]] = [[]]
    size = 0
    for event in events:
        length = len(json.dumps(event, default=str))
        if batches[-1] and (len(batches[-1]) >= MAX_EVENTS_PER_BATCH or size + length > MAX_BATCH_BYTES):
            batches.append([])
            size = 0
        batches[-1].append(event)
        size += length
    return [batch for batch in batches if batch]


# Renamed before reading so hooks keep appending to a fresh spool; an unsent batch waits for the next drain.
def drain(folder: Path, post: Any) -> dict[str, Any] | None:
    import fcntl  # noqa: PLC0415 - POSIX: the device runs on macOS / Linux (WSL2)

    if not folder.is_dir():
        return None
    descriptor = os.open(str(folder / LOCK_FILE), os.O_RDWR | os.O_CREAT, 0o600)
    answer = None
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        spool_path = folder / SPOOL_FILE
        if spool_path.exists():
            with contextlib.suppress(OSError):
                spool_path.rename(folder / f"{SENDING_PREFIX}{time.time_ns()}.jsonl")
        for pending in sorted(folder.glob(f"{SENDING_PREFIX}*.jsonl")):
            events = []
            for line in pending.read_text(encoding="utf-8", errors="replace").splitlines():
                with contextlib.suppress(ValueError):
                    events.append(json.loads(line))
            sent = True
            for batch in _batches(events):
                result = post({"events": batch})
                if result is None:
                    sent = False
                    break
                answer = result
            if not sent:
                break  # the platform is not reachable now: everything stays for the next drain
            pending.unlink(missing_ok=True)
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)
    return answer
