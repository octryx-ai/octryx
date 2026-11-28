from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Session, WorkerDelegation
from ..schemas.operations.coordinator import CoordinatorStateContract
from .coordinator_mode_contracts import (
    _determine_metadata_mode,
    _direct_contract,
    _normalize_ids,
    _worker_delegation_contract,
)


async def _resolve_root_session(db: AsyncSession, session_id: str) -> Session | None:
    current = await db.get(Session, session_id)
    if current is None:
        return None
    while current.parent_session_id:
        parent = await db.get(Session, current.parent_session_id)
        if parent is None:
            break
        current = parent
    return current


async def load_coordinator_state_contract(
    db: AsyncSession,
    *,
    session_id: str,
) -> CoordinatorStateContract | None:
    root_session = await _resolve_root_session(db, session_id)
    if root_session is None:
        return None

    child_session_ids = await _child_session_ids(db, root_session)
    delegations = (
        (
            await db.execute(
                select(WorkerDelegation)
                .where(WorkerDelegation.source_session_id == root_session.id)
                .order_by(WorkerDelegation.created_at.asc())
            )
        )
        .scalars()
        .all()
    )
    if delegations:
        return _worker_delegation_contract(root_session, delegations=delegations, child_session_ids=child_session_ids)

    metadata_mode = _determine_metadata_mode(root_session)
    direct_contract = _direct_contract(root_session, child_session_ids)
    if metadata_mode == "deterministic_workflow":
        direct_contract = direct_contract.model_copy(update={"coordinator_mode": metadata_mode})
    return direct_contract


async def _child_session_ids(db: AsyncSession, root_session: Session) -> list[str]:
    child_sessions = (
        (
            await db.execute(
                select(Session).where(Session.parent_session_id == root_session.id).order_by(Session.started_at.asc())
            )
        )
        .scalars()
        .all()
    )
    return _normalize_ids([row.id for row in child_sessions])


__all__ = ["load_coordinator_state_contract"]
