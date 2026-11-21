"""The scope of one governed write: what it touched, its commit guard, and its records."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ...models import AgentDefinition, AgentStep
from ..agent_definition_writers import AgentDefinitionWriter

AUDIT_ACTION = "agent_definition.write"
AUDIT_RESOURCE_TYPE = "agent_definition"

#: Outcomes recorded on the audit row. Explicit states, no inference.
OUTCOME_RECORDED = "revision_recorded"
OUTCOME_PUBLISHED = "revision_published"
OUTCOME_INVALID = "revision_recorded_invalid"
OUTCOME_DELETED = "definition_deleted"
OUTCOME_UNCHANGED = "unchanged"


@dataclass(slots=True)
class _TouchedDefinitions:
    """Definition ids the enclosed writer touched, and which it deleted."""

    written: set[str] = field(default_factory=set)
    deleted: set[str] = field(default_factory=set)
    #: Workspace (project) id per definition, captured in ``before_flush`` while the
    #: row is still loaded. It is the only attribution a *deleted* definition can
    #: still be audited with, because by finalization the row is gone.
    project_ids: dict[str, str] = field(default_factory=dict)


#: Session attribute holding the open scope's commit guard. One guard per session,
#: shared by nested scopes so that exactly one of them owns the transaction.
_COMMIT_GUARD_ATTR = "_agent_definition_governed_commit_guard"


@dataclass(slots=True)
class _CommitGuard:
    """Turns a writer-internal ``commit()`` into a flush for the scope's duration.

    The guard is what makes the governed write atomic: the writer's own
    ``commit()`` does not end the transaction, so the live row cannot be
    persisted before the boundary has validated it, appended the immutable
    revision, and written the audit entry. The request is remembered so the
    outermost scope can honour it once finalization is in the same transaction.
    """

    session: AsyncSession
    depth: int = 0
    commit_requested: bool = False

    async def deferred_commit(self) -> None:
        self.commit_requested = True
        await self.session.flush()


def _acquire_commit_guard(db: AsyncSession) -> tuple[_CommitGuard, bool]:
    """Install (or join) the session's commit guard; True when this scope owns it."""
    guard = getattr(db, _COMMIT_GUARD_ATTR, None)
    outermost = guard is None
    if guard is None:
        guard = _CommitGuard(session=db)
        # Instance attribute only: releasing the guard deletes it and the class
        # method is in force again.
        db.commit = guard.deferred_commit  # type: ignore[method-assign]
        setattr(db, _COMMIT_GUARD_ATTR, guard)
    guard.depth += 1
    return guard, outermost


def _release_commit_guard(db: AsyncSession, guard: _CommitGuard) -> None:
    """Restore ``commit()`` once the outermost scope is done with it."""
    guard.depth -= 1
    if guard.depth > 0:
        return
    for attribute in ("commit", _COMMIT_GUARD_ATTR):
        try:
            delattr(db, attribute)
        except AttributeError:  # pragma: no cover - the scope installed both
            pass


@dataclass(frozen=True, slots=True)
class GovernedWriteRecord:
    """What the boundary did for one definition. Returned for tests and callers."""

    definition_id: str
    writer: AgentDefinitionWriter
    outcome: str
    revision_id: str | None = None
    revision_number: int | None = None
    revision_status: str | None = None
    project_id: str | None = None
    checksum: str | None = None
    issue_codes: tuple[str, ...] = ()


@dataclass(slots=True)
class GovernedWriteScope:
    """Handle for an open governed write. Exposes the result after the scope."""

    writer: AgentDefinitionWriter
    actor_id: str
    records: list[GovernedWriteRecord] = field(default_factory=list)

    def record_for(self, definition_id: str) -> GovernedWriteRecord | None:
        for record in self.records:
            if record.definition_id == definition_id:
                return record
        return None


def _collect_touched(session: Any, touched: _TouchedDefinitions) -> None:
    """Record every aggregate row in this flush, keyed by definition id."""
    for instance in session.deleted:
        if isinstance(instance, AgentDefinition):
            touched.written.add(str(instance.id))
            touched.deleted.add(str(instance.id))
            _capture_project(instance, touched)
        elif isinstance(instance, AgentStep):
            touched.written.add(str(instance.agent_id))
    for instance in (*session.new, *session.dirty):
        if isinstance(instance, AgentDefinition):
            touched.written.add(str(instance.id))
            _capture_project(instance, touched)
        elif isinstance(instance, AgentStep):
            touched.written.add(str(instance.agent_id))


def _capture_project(definition: AgentDefinition, touched: _TouchedDefinitions) -> None:
    project_id = str(definition.project_id or "")
    if project_id:
        touched.project_ids[str(definition.id)] = project_id
