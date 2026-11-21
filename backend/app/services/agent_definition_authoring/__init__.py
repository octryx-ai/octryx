"""The one governed write boundary for the Agent Definition aggregate.

The aggregate has an immutable revision and publication contract, but on its
own the contract is advisory: every other writer could mutate the live
``AgentDefinition`` / ``AgentStep`` rows around it, with no validation verdict, no
immutable record, and no attributable audit entry. This module is the boundary
those writers pass through — all ten of them, inventoried in
:mod:`app.services.agent_definition_writers`, including the one that never names the
aggregate at all and reaches it through ``AgentGroup.agents``.

How it works
------------

A writer wraps its body in :func:`governed_agent_definition_write` (or carries
the :func:`governs_agent_definition_write` decorator, which is the same thing for
a writer whose signature already exposes the actor). For the duration of the
scope a ``before_flush`` listener on the session collects the definition ids that
the enclosed code touches — directly or through an ``AgentStep`` — so a writer
needs no manual bookkeeping. Collection is automatic; the *writer identity* never
is: it is passed explicitly and recorded.

On clean exit the scope flushes once more *while the collector is still
attached* — a writer that only staged rows is collected too — and then, for each
collected definition:

1. rebuilds the canonical snapshot and its checksum;
2. records the explicit ``unchanged`` outcome if the checksum equals the
   definition's newest revision: no revision is appended, but the governed write
   still leaves evidence instead of no trace at all;
3. validates the snapshot and appends an immutable revision carrying the verdict
   (``draft`` when clean, ``invalid`` with the typed issue list when not);
4. publishes that revision **only** for the ``bootstrap`` writer class, whose
   content is a repository constant already gated;
5. writes one ``AuditLog`` row recording actor, writer, writer class, definition
   id, revision id and number, Workspace, checksum, and outcome — including for a
   deletion, whose Workspace attribution is captured while the row is still
   loaded.

What it deliberately does not do
--------------------------------

It never refuses a live write that panel CRUD accepts, and it never
publishes a production write. Refusal stays at ``publish_revision``, and what
makes publication actually bite is the runtime resolution boundary
(:mod:`app.services.agent_definition_execution`), not a new gate here.

Transaction boundary: **the boundary is the single transaction owner.** Several
inventoried writers ``commit()`` inside their own body; left alone that persists
the live aggregate before it has been validated, before the immutable revision
exists, and before anything was audited — so a failure in between would leave an
authored row with no revision and no audit entry. While a governed scope is open,
``commit()`` on the session therefore only flushes and records the request, and
the outermost scope performs the real commit *after* finalization. Writers that do
not commit (package import) keep their existing semantics:
``app.db.get_db`` commits once the request handler returns, and ``seed_database``
commits at the end of bootstrap. Either way the authored change, the revision, and
the audit row commit together or roll back together.

Secret safety: the audit ``details`` carry the writer key, the outcome, ids, the
snapshot checksum, and the typed validation issue *codes*. No prompt text, step
instruction, tool argument, credential, or exception string is recorded — the same
rule ``ValidationIssue`` already follows.
"""

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
    """Open the governed write boundary around an aggregate mutation.

    *actor_id* must be a real ``users.id``: it is the audit attribution and the
    publishing identity for bootstrap writers. An empty actor is a programming
    error, not a tolerated anonymous write.
    """
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
    """Wrap one writer function in the governed boundary.

    For writers whose signature already carries the session and the actor this is
    a one-line binding, which is what keeps oversized writer modules from growing
    a block of boilerplate per function. *actor_param* may name either a user id
    or a ``User``; anything exposing ``.id`` is reduced to it.
    """

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
