"""The one governed write boundary for the Agent Definition aggregate."""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from functools import wraps
from typing import Any

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession

from ..agent_definition_writers import AgentDefinitionWriter

# Callers and tests reach ``_finalize`` through this module, so the scope below resolves it here.
from .finalize import _finalize
from .scope import (
    AUDIT_ACTION,
    AUDIT_RESOURCE_TYPE,
    OUTCOME_DELETED,
    OUTCOME_INVALID,
    OUTCOME_PUBLISHED,
    OUTCOME_RECORDED,
    OUTCOME_UNCHANGED,
    GovernedWriteRecord,
    GovernedWriteScope,
    _acquire_commit_guard,
    _collect_touched,
    _release_commit_guard,
    _TouchedDefinitions,
)


@asynccontextmanager
async def governed_agent_definition_write(
    db: AsyncSession,
    *,
    writer: AgentDefinitionWriter,
    actor_id: str,
) -> AsyncIterator[GovernedWriteScope]:
    """Open the governed write boundary around an aggregate mutation."""
    resolved_actor = str(actor_id or "").strip()
    if not resolved_actor:
        raise ValueError("governed agent definition writes require an actor id")
    scope = GovernedWriteScope(writer=writer, actor_id=resolved_actor)
    touched = _TouchedDefinitions()
    sync_session = db.sync_session


    def _listener(session: Any, _flush_context: Any, _instances: Any) -> None:
        _collect_touched(session, touched)

    event.listen(sync_session, "before_flush", _listener)
    guard, owns_transaction = _acquire_commit_guard(db)
    try:
        yield scope
        # The authored change is flushed one last time here, while the collector is
        # still attached: a writer that only staged rows without flushing is still
        # collected, and no aggregate row reaches the database after collection
        # stops. Nothing is committed yet.
        await db.flush()
    finally:
        # Detach before finalizing so the boundary's own flushes cannot feed the
        # collector, and so a failing writer leaves neither listener nor guard
        # behind.
        event.remove(sync_session, "before_flush", _listener)
        _release_commit_guard(db, guard)
    await _finalize(db, scope=scope, touched=touched)
    if owns_transaction and guard.commit_requested:
        # One transaction owner: the enclosed writer asked to commit, and the
        # commit happens only now, with the revision and the audit row in it.
        await db.commit()


def governs_agent_definition_write(
    writer: AgentDefinitionWriter,
    *,
    actor_param: str,
    db_param: str = "db",
) -> Callable[[Callable[..., Awaitable[Any]]], Callable[..., Awaitable[Any]]]:
    """Wrap one writer function in the governed boundary."""

    def decorate(func: Callable[..., Awaitable[Any]]) -> Callable[..., Awaitable[Any]]:
        @wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            db = kwargs.get(db_param) if db_param in kwargs else (args[0] if args else None)
            if not isinstance(db, AsyncSession):
                raise TypeError(
                    f"{func.__qualname__} must receive its AsyncSession as "
                    f"{db_param!r} or as the first positional argument"
                )
            actor = kwargs[actor_param]
            actor_id = str(getattr(actor, "id", actor) or "")
            async with governed_agent_definition_write(
                db, writer=writer, actor_id=actor_id
            ):
                return await func(*args, **kwargs)

        return wrapper

    return decorate


__all__ = [
    "AUDIT_ACTION",
    "AUDIT_RESOURCE_TYPE",
    "OUTCOME_DELETED",
    "OUTCOME_INVALID",
    "OUTCOME_PUBLISHED",
    "OUTCOME_RECORDED",
    "OUTCOME_UNCHANGED",
    "GovernedWriteRecord",
    "GovernedWriteScope",
    "governed_agent_definition_write",
    "governs_agent_definition_write",
]
