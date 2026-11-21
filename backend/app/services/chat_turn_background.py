"""Background task helpers for chat-turn work outside the foreground run path."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable

logger = logging.getLogger(__name__)

_CHAT_TURN_BACKGROUND_TASKS: dict[str, set[asyncio.Task]] = {}


def schedule_chat_turn_background_task(
    *,
    session_id: str,
    task_name: str,
    coro_factory: Callable[[], Awaitable[None]],
) -> asyncio.Task:
    """Schedule bounded chat-turn follow-up work without extending the foreground run task."""

    async def _runner() -> None:
        await asyncio.sleep(0)
        await coro_factory()

    task = asyncio.create_task(_runner(), name=f"chat-turn-background:{task_name}:{session_id}")
    bucket = _CHAT_TURN_BACKGROUND_TASKS.setdefault(session_id, set())
    bucket.add(task)

    def _cleanup(done_task: asyncio.Task) -> None:
        bucket.discard(done_task)
        if not bucket:
            _CHAT_TURN_BACKGROUND_TASKS.pop(session_id, None)
        if done_task.cancelled():
            logger.info(
                "chat.turn.background.cancelled",
                extra={"session_id": session_id, "task_name": task_name},
            )
            return
        exc = done_task.exception()
        if exc is not None:
            logger.exception(
                "chat.turn.background.failed",
                exc_info=exc,
                extra={"session_id": session_id, "task_name": task_name},
            )
            return
        logger.info(
            "chat.turn.background.completed",
            extra={"session_id": session_id, "task_name": task_name},
        )

    task.add_done_callback(_cleanup)
    logger.info(
        "chat.turn.background.scheduled",
        extra={"session_id": session_id, "task_name": task_name},
    )
    return task


def list_chat_turn_background_tasks(session_id: str | None = None) -> list[asyncio.Task]:
    if session_id is not None:
        return list(_CHAT_TURN_BACKGROUND_TASKS.get(session_id, set()))
    tasks: list[asyncio.Task] = []
    for bucket in _CHAT_TURN_BACKGROUND_TASKS.values():
        tasks.extend(bucket)
    return tasks


async def drain_chat_turn_background_tasks(session_id: str | None = None) -> None:
    tasks = [task for task in list_chat_turn_background_tasks(session_id) if not task.done()]
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)


async def cancel_chat_turn_background_tasks(session_id: str | None = None) -> None:
    tasks = [task for task in list_chat_turn_background_tasks(session_id) if not task.done()]
    for task in tasks:
        task.cancel()
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)
