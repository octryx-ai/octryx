"""The in-process registry of running chat-turn tasks, keyed by session id. Every path that starts or resumes a turn
registers here, so stop, the running state and the test harness see one registry."""

from __future__ import annotations

import asyncio
from typing import Any

from ..runtime_ownership.process_identity import current_process_id

CHAT_RUN_TASKS: dict[str, asyncio.Task] = {}


def register_turn_task(session_id: str, task: asyncio.Task) -> None:
    CHAT_RUN_TASKS[session_id] = task


def release_turn_task(session_id: str, task: asyncio.Task | None) -> None:
    # A newer turn keeps its own entry.
    if task is not None and CHAT_RUN_TASKS.get(session_id) is task:
        CHAT_RUN_TASKS.pop(session_id, None)


def effective_session_status(session: Any) -> str:
    status = session.status or "active"
    if status != "running":
        return status
    task = CHAT_RUN_TASKS.get(session.id)
    if task and not task.done():
        return "running"
    owner = getattr(session, "turn_owner_process_id", None)
    if owner and owner != current_process_id():
        return "running"
    return "active"


__all__ = ["CHAT_RUN_TASKS", "effective_session_status", "register_turn_task", "release_turn_task"]
