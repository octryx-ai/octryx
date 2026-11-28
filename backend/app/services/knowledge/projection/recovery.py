"""Governed recovery of a stuck projection obligation: requeue or retry now, compare-and-set. Each state change commits
with exactly one audit record."""

from __future__ import annotations

import logging
from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ....models.project.knowledge_evidence import (
    OUTBOX_OPERATION_PARSE_REVISION,
    OUTBOX_OPERATION_PROJECT_REVISION,
    OUTBOX_STATE_DEAD_LETTER,
    OUTBOX_STATE_PENDING,
    KnowledgeProjectionOutboxEntry,
)
from ....models.security.compliance_audit import AUDIT_RUNTIME_ACTION, OUTCOME_ALLOWED
from ....time_utils import utc_now
from ...compliance_audit.service import create_audit_record
from ...request_context import get_current_request_id, safe_request_id
from ..access.authorization import AuthorizedWorkspace, WorkspaceWriteForbiddenError
from ..ledger.errors import EvidenceLedgerContractError, EvidenceRecordNotFoundError
from .recovery_vocabulary import (
    _MAX_ACTOR_ROLE_CHARS,
    _MAX_ID_CHARS,
    ALL_RECOVERY_OPERATIONS,
    AUDIT_RESOURCE_TYPE,
    RECOVERY_RESULT_REQUEUED,
    RECOVERY_RESULT_RETRY_SCHEDULED,
    REQUEUE_OPERATIONS,
    ProjectionRecovery,
    _audit_details,
    _Obligation,
    _refused,
)

logger = logging.getLogger(__name__)


async def _load(db: AsyncSession, project_id: str, revision_id: str, now: datetime) -> _Obligation:
    # Scoped by ``project_id``: another Workspace's revision is absent, not forbidden (the same 404).
    rows = (
        await db.execute(
            select(
                KnowledgeProjectionOutboxEntry.id,
                KnowledgeProjectionOutboxEntry.state,
                KnowledgeProjectionOutboxEntry.next_attempt_at,
                KnowledgeProjectionOutboxEntry.operation,
            ).where(
                KnowledgeProjectionOutboxEntry.project_id == project_id,
                KnowledgeProjectionOutboxEntry.revision_id == revision_id,
                KnowledgeProjectionOutboxEntry.operation.in_(
                    (OUTBOX_OPERATION_PROJECT_REVISION, OUTBOX_OPERATION_PARSE_REVISION)
                ),
            )
        )
    ).all()
    row = next((item for item in rows if item[3] == OUTBOX_OPERATION_PROJECT_REVISION), rows[0] if rows else None)
    if row is None:
        raise EvidenceRecordNotFoundError()
    return _Obligation(entry_id=row[0], state=row[1], next_attempt_at=row[2], due=row[2] <= now)


def _may_apply(obligation: _Obligation, operation: str) -> bool:
    if operation in REQUEUE_OPERATIONS:
        return obligation.state == OUTBOX_STATE_DEAD_LETTER
    return obligation.state == OUTBOX_STATE_PENDING and not obligation.due


async def _apply(
    db: AsyncSession, project_id: str, obligation: _Obligation, operation: str, now: datetime
) -> bool:
    # The WHERE repeats the read state, so a concurrent claim or recovery invalidates this update instead of overwriting
    # it.
    if operation in REQUEUE_OPERATIONS:
        conditions = (KnowledgeProjectionOutboxEntry.state == OUTBOX_STATE_DEAD_LETTER,)
        # ``projected_through_ordinal`` is deliberately absent: the cursor is
        # already-projected work, and rewinding it would re-upsert spans.
        values: dict[str, object] = {
            "state": OUTBOX_STATE_PENDING,
            "attempt_count": 0,
            "claimed_by": None,
            "claimed_at": None,
            "claimed_until": None,
            "next_attempt_at": now,
            "last_failure": None,
            "applied_at": None,
            "updated_at": now,
        }
    else:
        conditions = (
            KnowledgeProjectionOutboxEntry.state == OUTBOX_STATE_PENDING,
            # ``retry_now`` keeps the row in ``pending``, so state alone is not a
            # generation token. Match the exact schedule value that this request
            # observed: if another retry moved it first, this update must lose even
            # when the winning request used a later application-clock timestamp.
            KnowledgeProjectionOutboxEntry.next_attempt_at == obligation.next_attempt_at,
            # Only a scheduled attempt can be pulled forward; an already-due one has
            # nothing to change, which is what makes the repeat a no-op.
            KnowledgeProjectionOutboxEntry.next_attempt_at > now,
        )
        values = {"next_attempt_at": now, "updated_at": now}
    result = await db.execute(
        update(KnowledgeProjectionOutboxEntry)
        .where(
            KnowledgeProjectionOutboxEntry.id == obligation.entry_id,
            KnowledgeProjectionOutboxEntry.project_id == project_id,
            *conditions,
        )
        .values(**values)
    )
    return result.rowcount == 1


async def _add_audit_record(
    db: AsyncSession, *, authorized: AuthorizedWorkspace, actor_user_id: str | None, recovery: ProjectionRecovery
) -> None:
    # ``commit=False`` keeps the audit record atomic with the state change.
    if actor_user_id is not None and (type(actor_user_id) is not str or len(actor_user_id) > _MAX_ID_CHARS):
        raise EvidenceLedgerContractError()
    if len(authorized.role) > _MAX_ACTOR_ROLE_CHARS:
        raise EvidenceLedgerContractError()
    await create_audit_record(
        db,
        event_type=AUDIT_RUNTIME_ACTION,
        resource_type=AUDIT_RESOURCE_TYPE,
        resource_id=recovery.entry_id,
        actor_user_id=actor_user_id,
        actor_role=authorized.role,
        outcome=OUTCOME_ALLOWED,
        project_id=authorized.project_id,
        details=_audit_details(recovery),
        # The request's own correlation token, already bounded to 64 safe characters
        # by the request-context owner; never a caller-chosen free string.
        request_id=safe_request_id(get_current_request_id()),
        commit=False,
    )


async def recover_projection(
    db: AsyncSession,
    *,
    authorized: AuthorizedWorkspace,
    revision_id: object,
    operation: str,
    actor_user_id: str | None,
) -> ProjectionRecovery:
    _check_request(authorized, revision_id, operation)

    project_id = authorized.project_id
    now = utc_now()
    obligation = await _load(db, project_id, revision_id, now)
    if not _may_apply(obligation, operation):
        return _refused(obligation, revision_id, operation)
    if not await _apply(db, project_id, obligation, operation, now):
        # The row moved between the read and the compare-and-set: discard this
        # request's intent and answer from the state that actually won.
        await db.rollback()
        return _refused(await _load(db, project_id, revision_id, utc_now()), revision_id, operation)

    recovery = ProjectionRecovery(
        entry_id=obligation.entry_id,
        revision_id=revision_id,
        operation=operation,
        previous_state=obligation.state,
        result=RECOVERY_RESULT_REQUEUED if operation in REQUEUE_OPERATIONS else RECOVERY_RESULT_RETRY_SCHEDULED,
        outbox_state=OUTBOX_STATE_PENDING,
    )
    await _commit_with_record(db, authorized=authorized, actor_user_id=actor_user_id, recovery=recovery)
    logger.info(
        "Knowledge projection recovered: operation=%s previous_state=%s result=%s workspace=%s",
        recovery.operation,
        recovery.previous_state,
        recovery.result,
        project_id,
    )
    return recovery


def _check_request(authorized: AuthorizedWorkspace, revision_id: object, operation: str) -> None:
    if type(authorized) is not AuthorizedWorkspace or operation not in ALL_RECOVERY_OPERATIONS:
        raise EvidenceLedgerContractError()
    if not authorized.may_author:
        # The transport already authorizes; re-checked here so a non-HTTP caller
        # cannot mutate delivery state with a reader's role.
        raise WorkspaceWriteForbiddenError()
    if type(revision_id) is not str or not 0 < len(revision_id) <= _MAX_ID_CHARS:
        raise EvidenceRecordNotFoundError()


async def _commit_with_record(
    db: AsyncSession, *, authorized: AuthorizedWorkspace, actor_user_id: str | None, recovery: ProjectionRecovery
) -> None:
    try:
        await _add_audit_record(db, authorized=authorized, actor_user_id=actor_user_id, recovery=recovery)
        # One commit for the transition and its record.
        await db.commit()
    except Exception:
        # A record that cannot be written un-does the recovery: an unaudited
        # transition of durable delivery state is worse than no transition.
        await db.rollback()
        raise
