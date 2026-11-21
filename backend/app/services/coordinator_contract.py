from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Session, SubAgentGroup, ToolCall, WorkerDelegation
from ..schemas.operations.coordinator import CoordinatorStateContract
from .coordinator_document_flow import _build_document_flow_summary
from .coordinator_mode_contracts import (
    _determine_metadata_mode,
    _direct_contract,
    _normalize_ids,
    _sub_agent_group_contract,
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
    related_session_ids = _normalize_ids([root_session.id] + child_session_ids)
    tool_calls = await _related_tool_calls(db, related_session_ids)
    document_flow = _build_document_flow_summary(root_session, tool_calls=tool_calls)

    active_group = await _active_sub_agent_group(db, root_session)
    if active_group is not None:
        payload = _sub_agent_group_contract(root_session, group=active_group, child_session_ids=child_session_ids)
        return _with_document_flow(payload, document_flow)

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
        payload = _worker_delegation_contract(
            root_session,
            delegations=delegations,
            child_session_ids=child_session_ids,
        )
        return _with_document_flow(payload, document_flow)

    metadata_mode = _determine_metadata_mode(root_session)
    direct_contract = _direct_contract(root_session, child_session_ids)
    if metadata_mode == "deterministic_workflow":
        direct_contract = direct_contract.model_copy(update={"coordinator_mode": metadata_mode})
    return _with_document_flow(direct_contract, document_flow)


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


async def _related_tool_calls(db: AsyncSession, related_session_ids: list[str]) -> list[ToolCall]:
    return (
        (
            await db.execute(
                select(ToolCall).where(ToolCall.session_id.in_(related_session_ids)).order_by(ToolCall.created_at.asc())
            )
        )
        .scalars()
        .all()
        if related_session_ids
        else []
    )


async def _active_sub_agent_group(db: AsyncSession, root_session: Session) -> SubAgentGroup | None:
    """The session's current sub-agent group, else its newest one."""
    metadata = dict(root_session.metadata_ or {})
    current_group_id = str(metadata.get("current_sub_agent_group_id") or "").strip()
    group_stmt = select(SubAgentGroup).where(SubAgentGroup.parent_session_id == root_session.id)
    if current_group_id:
        group_stmt = group_stmt.order_by(SubAgentGroup.id.desc())
    else:
        group_stmt = group_stmt.order_by(SubAgentGroup.created_at.desc())
    groups = (await db.execute(group_stmt)).scalars().all()

    active_group = None
    if current_group_id:
        active_group = next((row for row in groups if row.id == current_group_id), None)
    if active_group is None and groups:
        active_group = groups[0]
    return active_group


def _with_document_flow(
    payload: CoordinatorStateContract, document_flow: dict[str, str | int | bool | None] | None
) -> CoordinatorStateContract:
    if document_flow is not None:
        return payload.model_copy(update={"document_flow": document_flow})
    return payload


__all__ = ["load_coordinator_state_contract"]
