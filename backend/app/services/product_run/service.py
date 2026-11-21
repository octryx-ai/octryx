"""Product Run persistence: open a run, move its attempt, keep the audit.

Every write happens inside one SAVEPOINT, so a refused or concurrent transition
leaves neither a state change nor an audit row behind, and the caller's
transaction stays usable. The service flushes but never commits: the caller owns
the transaction boundary.

State moves are compare-and-set on ``(workspace, state, version)`` of both the run
and its attempt, so a handle carrying another Workspace can never write audit.
The audit ``sequence`` equals the run's version after the move, so it is gap-free
per run and needs no extra read.

Rows are written with Core statements, and any run or attempt object the caller
already holds in the session is reloaded after a move, so a later read in the same
session never sees a superseded state.

Execution-gate facts are write-once: they are accepted only on the gate's decision
for a requested attempt, and only with the status and source that decision implies.

Errors carry a stable ``code`` and a fixed message; no identifier, state value, or
database text is ever placed into an error.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, replace

from sqlalchemy import insert, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.util import identity_key

from ...models import Session as ChatSession
from ...models.runtime.product_run import (
    RUN_ORIGINS,
    RUN_STATE_RUNNING,
    RUN_WORKSPACE_SOURCE_SESSION_PROJECT,
    TRANSITION_ACTOR_RUNTIME,
    TRANSITION_ACTORS,
    ProductRun,
    ProductRunAttempt,
    ProductRunTransition,
)
from ...time_utils import utc_now
from ..knowledge.identity.workspace import WorkspaceId
from ..runtime_ownership.process_identity import current_process_id
from ..session.turn_execution_snapshot import GATE_SOURCES, GATE_STATUSES, UNKNOWN_VALUE, safe_token
from .errors import (
    IllegalProductRunTransitionError,
    InvalidProductRunInputError,
    ProductRunPersistenceError,
    ProductRunScopeError,
    StaleProductRunTransitionError,
)
from .states import (
    ACTIVE_STATES,
    INITIAL_STATE,
    TERMINAL_STATES,
    gate_facts_match,
    is_legal_end_reason,
    is_legal_transition,
    requires_gate_facts,
)

_EXECUTION_PROFILE_ID_MAX = 160
# An unknown profile status is recorded as the snapshot's closed ``unknown`` value.
_RECORDABLE_GATE_STATUSES = GATE_STATUSES | {UNKNOWN_VALUE}


@dataclass(frozen=True, slots=True)
class ProductRunHandle:
    """The caller's view of one open attempt; every move returns a fresh handle."""

    run_id: str
    attempt_id: str
    workspace_id: str
    state: str
    run_version: int
    attempt_version: int


@dataclass(frozen=True, slots=True)
class GateFacts:
    """Allow-listed execution-gate facts recorded on the attempt."""

    status: str
    decision_source: str
    execution_profile_id: str | None = None


def _canonical_uuid(value: object) -> str:
    if not isinstance(value, str):
        raise InvalidProductRunInputError()
    try:
        parsed = uuid.UUID(value)
    except ValueError as exc:
        raise InvalidProductRunInputError() from exc
    if str(parsed) != value:
        raise InvalidProductRunInputError()
    return value


def _validated_gate(gate: GateFacts) -> GateFacts:
    if gate.status not in _RECORDABLE_GATE_STATUSES or gate.decision_source not in GATE_SOURCES:
        raise InvalidProductRunInputError()
    profile_id = gate.execution_profile_id
    if profile_id is not None and (safe_token(profile_id) != profile_id or len(profile_id) > _EXECUTION_PROFILE_ID_MAX):
        raise InvalidProductRunInputError()
    return gate


def _checked_gate(handle: ProductRunHandle, to_state: str, end_reason: str | None, gate: GateFacts | None):
    if not requires_gate_facts(handle.state, to_state):
        if gate is not None:
            raise IllegalProductRunTransitionError()
        return None
    if gate is None:
        raise IllegalProductRunTransitionError()
    facts = _validated_gate(gate)
    if not gate_facts_match(end_reason, facts.status, facts.decision_source):
        raise IllegalProductRunTransitionError()
    return facts


async def _refresh_cached(db: AsyncSession, handle: ProductRunHandle) -> None:
    # Expiring would force a synchronous lazy load on the next attribute access,
    # which an async session cannot do; reload only what the caller already holds.
    identity_map = db.sync_session.identity_map
    for model, key in ((ProductRun, handle.run_id), (ProductRunAttempt, handle.attempt_id)):
        cached = identity_map.get(identity_key(model, key))
        if cached is not None:
            await db.refresh(cached)


async def open_run(
    db: AsyncSession,
    *,
    workspace_id: WorkspaceId,
    owner_user_id: str,
    session_id: str,
    origin: str,
    turn_user_message_id: str | None = None,
    actor: str = TRANSITION_ACTOR_RUNTIME,
) -> ProductRunHandle:
    """Open a run with its first attempt in ``requested`` and audit it.

    The Workspace must be the session's own project and the owner the session's
    user; anything else is refused before a row is written. The session row is
    locked for the rest of the caller's transaction where the database supports it.
    """
    if type(workspace_id) is not WorkspaceId or origin not in RUN_ORIGINS or actor not in TRANSITION_ACTORS:
        raise InvalidProductRunInputError()
    owner = _canonical_uuid(owner_user_id)
    session_key = _canonical_uuid(session_id)
    message_key = None if turn_user_message_id is None else _canonical_uuid(turn_user_message_id)
    workspace = workspace_id.canonical

    row = (
        await db.execute(
            select(ChatSession.user_id, ChatSession.project_id).where(ChatSession.id == session_key).with_for_update()
        )
    ).one_or_none()
    if row is None or row.user_id != owner or row.project_id != workspace:
        raise ProductRunScopeError()

    now = utc_now()
    run_id = str(uuid.uuid4())
    attempt_id = str(uuid.uuid4())
    try:
        async with db.begin_nested():
            await db.execute(
                insert(ProductRun).values(
                    id=run_id,
                    workspace_id=workspace,
                    owner_user_id=owner,
                    session_id=session_key,
                    turn_user_message_id=message_key,
                    origin=origin,
                    workspace_source=RUN_WORKSPACE_SOURCE_SESSION_PROJECT,
                    state=INITIAL_STATE,
                    attempt_count=1,
                    version=1,
                    created_at=now,
                    updated_at=now,
                )
            )
            await db.execute(
                insert(ProductRunAttempt).values(
                    id=attempt_id,
                    run_id=run_id,
                    workspace_id=workspace,
                    attempt_number=1,
                    state=INITIAL_STATE,
                    owner_process_id=current_process_id(),
                    version=1,
                    created_at=now,
                )
            )
            await db.execute(
                insert(ProductRunTransition).values(
                    id=str(uuid.uuid4()),
                    run_id=run_id,
                    attempt_id=attempt_id,
                    workspace_id=workspace,
                    sequence=1,
                    from_state=None,
                    to_state=INITIAL_STATE,
                    actor=actor,
                    recorded_at=now,
                )
            )
    except IntegrityError as exc:
        raise ProductRunPersistenceError() from exc
    return ProductRunHandle(run_id, attempt_id, workspace, INITIAL_STATE, 1, 1)


async def transition(
    db: AsyncSession,
    handle: ProductRunHandle,
    *,
    to_state: str,
    end_reason: str | None = None,
    actor: str = TRANSITION_ACTOR_RUNTIME,
    gate: GateFacts | None = None,
    final_trace_id: str | None = None,
) -> ProductRunHandle:
    """Move the attempt (and the run's mirrored state) from ``handle.state``.

    Raises :class:`IllegalProductRunTransitionError` for a move, end reason or gate
    facts outside the closed tables and :class:`StaleProductRunTransitionError` when
    the stored Workspace, state or version no longer matches the handle. Neither
    leaves a row behind.
    """
    if actor not in TRANSITION_ACTORS:
        raise InvalidProductRunInputError()
    if not is_legal_transition(handle.state, to_state) or not is_legal_end_reason(handle.state, to_state, end_reason):
        raise IllegalProductRunTransitionError()
    gate_facts = _checked_gate(handle, to_state, end_reason, gate)
    trace_key = None if final_trace_id is None else _canonical_uuid(final_trace_id)

    now = utc_now()
    run_values: dict[str, object] = {
        "state": to_state,
        "end_reason": end_reason,
        "version": handle.run_version + 1,
        "updated_at": now,
    }
    attempt_values: dict[str, object] = {
        "state": to_state,
        "end_reason": end_reason,
        "version": handle.attempt_version + 1,
    }
    if to_state in TERMINAL_STATES:
        run_values["ended_at"] = now
        attempt_values["ended_at"] = now
    if to_state == RUN_STATE_RUNNING:
        attempt_values["started_at"] = now
    if to_state in ACTIVE_STATES:
        # The process moving an attempt into work owns it until it ends.
        attempt_values["owner_process_id"] = current_process_id()
    if gate_facts is not None:
        attempt_values["gate_status"] = gate_facts.status
        attempt_values["gate_decision_source"] = gate_facts.decision_source
        attempt_values["execution_profile_id"] = gate_facts.execution_profile_id
    if trace_key is not None:
        attempt_values["final_trace_id"] = trace_key

    try:
        async with db.begin_nested():
            run_result = await db.execute(
                update(ProductRun)
                .where(
                    ProductRun.id == handle.run_id,
                    ProductRun.workspace_id == handle.workspace_id,
                    ProductRun.state == handle.state,
                    ProductRun.version == handle.run_version,
                )
                .values(**run_values)
                .execution_options(synchronize_session=False)
            )
            if int(run_result.rowcount or 0) != 1:
                raise StaleProductRunTransitionError()
            attempt_result = await db.execute(
                update(ProductRunAttempt)
                .where(
                    ProductRunAttempt.id == handle.attempt_id,
                    ProductRunAttempt.run_id == handle.run_id,
                    ProductRunAttempt.workspace_id == handle.workspace_id,
                    ProductRunAttempt.state == handle.state,
                    ProductRunAttempt.version == handle.attempt_version,
                )
                .values(**attempt_values)
                .execution_options(synchronize_session=False)
            )
            if int(attempt_result.rowcount or 0) != 1:
                raise StaleProductRunTransitionError()
            await db.execute(
                insert(ProductRunTransition).values(
                    id=str(uuid.uuid4()),
                    run_id=handle.run_id,
                    attempt_id=handle.attempt_id,
                    workspace_id=handle.workspace_id,
                    sequence=handle.run_version + 1,
                    from_state=handle.state,
                    to_state=to_state,
                    end_reason=end_reason,
                    actor=actor,
                    recorded_at=now,
                )
            )
    except IntegrityError as exc:
        raise ProductRunPersistenceError() from exc
    await _refresh_cached(db, handle)
    return replace(
        handle,
        state=to_state,
        run_version=handle.run_version + 1,
        attempt_version=handle.attempt_version + 1,
    )


__all__ = [
    "GateFacts",
    "ProductRunHandle",
    "open_run",
    "transition",
]
