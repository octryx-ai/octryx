"""A turn the device refuses because it is full (``device_busy``) waits and is offered again, up to a limit."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from ...time_utils import utc_now
from ..observability.workflow_metrics import DEVICE_BUSY_WAIT

REASON = "device_busy"
CODE_SATURATED = "device_saturated"
_SETTINGS = json.loads(Path(__file__).with_name("busy_wait.json").read_text(encoding="utf-8"))
MAX_WAIT_SECONDS = float(_SETTINGS["max_wait_minutes"]) * 60
RETRY_SECONDS = float(_SETTINGS["retry_seconds"])


def is_busy(reason: str | None) -> bool:
    return str(reason or "").rsplit(":", 1)[-1].strip() == REASON


def waited_seconds(since: str | None) -> float:
    try:
        return max(0.0, (utc_now() - datetime.fromisoformat(str(since))).total_seconds()) if since else 0.0
    except ValueError:
        return 0.0


def saturated(waited: float) -> bool:
    return waited >= MAX_WAIT_SECONDS


def saturated_message(waited: float) -> str:
    minutes = max(1, round(waited / 60))
    return (f"The device was saturated for {minutes} min: it ran as many chats as it allows the whole time, so this "
            "turn could not start. Continue when one of its runs has finished, raise the device's parallel limit, "
            "or change where the run executes.")


def observe(path: str, outcome: str, waited: float) -> None:
    DEVICE_BUSY_WAIT.observe(waited, path=path, outcome=outcome)


__all__ = ["CODE_SATURATED", "MAX_WAIT_SECONDS", "REASON", "RETRY_SECONDS", "is_busy", "observe", "saturated",
           "saturated_message", "waited_seconds"]
