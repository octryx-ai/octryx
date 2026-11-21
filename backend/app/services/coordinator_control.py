from __future__ import annotations

import logging

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import async_session_factory
from ..models import Session
from ..schemas.operations.coordinator import CoordinatorControlAction, CoordinatorStateContract
from .coordinator_contract import load_coordinator_state_contract
from .prompt_catalog import prompt_set_scope, render_prompt
from .prompt_catalog.out_of_turn import prompt_set_for
from .session.collaboration import require_session_access
from .session.run_state import (
    RUN_STATUS_IN_PROGRESS,
    get_session_run_completion_reason,
)
from .session.stream import session_stream_manager
from .session.turn_refusals import TurnRefusal
from .session.turn_request import TurnRequest
from .session.turn_start import start_turn
from .session.turn_stop import stop_session_turn
from .sub_agent_group.service import _resume_parent_after_sub_agent_group

logger = logging.getLogger(__name__)

_STOP_UNSUPPORTED_DETAIL = "Coordinator stop is only supported for direct parent-session runs in phase 1."


async def apply_coordinator_control(
    db: AsyncSession,
    *,
    session_id: str,
    user_id: str,
    action: CoordinatorControlAction,
) -> CoordinatorStateContract:
    await require_session_access(db, session_id=session_id, user_id=user_id, require_write=True)
    contract = await load_coordinator_state_contract(db, session_id=session_id)
    if contract is None:
        raise HTTPException(status_code=404, detail="Session not found")

    root_session, _ = await require_session_access(
        db,
        session_id=contract.root_session_id,
        user_id=user_id,
        require_write=True,
    )
    if str(root_session.status or "").strip().lower() == "archived":
        raise HTTPException(status_code=409, detail="Archived threads must be restored before coordinator control")

    if action == "continue":
        return await _continue_coordinator_contract(db, contract=contract, root_session=root_session, user_id=user_id)
    if action == "stop":
        return await _stop_coordinator_contract(db, contract=contract, root_session=root_session)
    raise HTTPException(status_code=400, detail="Unsupported coordinator control action")


async def _continue_coordinator_contract(
    db: AsyncSession,
    *,
    contract: CoordinatorStateContract,
    root_session: Session,
    user_id: str,
) -> CoordinatorStateContract:
    if not contract.can_continue:
        raise HTTPException(status_code=409, detail="Coordinator session cannot continue in its current state")

    if contract.coordinator_mode == "sub_agent_group" and contract.sub_agent_group_id:
        await _resume_parent_after_sub_agent_group(
            session_factory=async_session_factory,
            group_id=contract.sub_agent_group_id,
        )
    else:
        metadata = root_session.metadata_ or {}
        # A control request has no turn prompt set: render for the coordinator session's Workspace.
        with prompt_set_scope(await prompt_set_for(db, workspace_id=root_session.project_id)):
            continue_prompt = _continue_prompt_for_contract(contract)
        started = await start_turn(
            TurnRequest(
                user_id=user_id,
                prompt=continue_prompt,
                session_id=root_session.id,
                project_id=root_session.project_id or "",
                runtime_target_id=str(metadata.get("runtime_target_id") or ""),
                agent_id=str(metadata.get("agent_definition_id") or ""),
                agent_type=str(root_session.agent_type or "diagnosis"),
                agent_type_explicit=False,
                project_id_explicit=True,
                runtime_target_id_explicit=True,
                thinking_level_explicit=True,
                thinking_level=str(metadata.get("thinking_level") or "light"),
            ),
            session_factory=async_session_factory,
        )
        if isinstance(started, TurnRefusal):
            # The chat-turn refusal this control always propagated.
            raise HTTPException(status_code=started.http_status, detail=started.detail)

    refreshed = await load_coordinator_state_contract(db, session_id=root_session.id)
    if refreshed is None:
        raise HTTPException(status_code=404, detail="Session not found")
    await _publish_coordinator_run_state(
        root_session.id,
        contract=refreshed,
        run_status=RUN_STATUS_IN_PROGRESS,
        run_completion_reason="",
    )
    return refreshed


async def _stop_coordinator_contract(
    db: AsyncSession,
    *,
    contract: CoordinatorStateContract,
    root_session: Session,
) -> CoordinatorStateContract:
    if not contract.can_stop:
        raise HTTPException(status_code=409, detail="Coordinator session cannot stop in its current state")
    if contract.coordinator_mode not in {"direct", "deterministic_workflow"}:
        raise HTTPException(status_code=409, detail=_STOP_UNSUPPORTED_DETAIL)

    await stop_session_turn(db, root_session)

    refreshed = await load_coordinator_state_contract(db, session_id=root_session.id)
    if refreshed is None:
        raise HTTPException(status_code=404, detail="Session not found")
    await _publish_coordinator_run_state(
        root_session.id,
        contract=refreshed,
        run_status=refreshed.run_status,
        run_completion_reason=get_session_run_completion_reason(root_session) or refreshed.run_completion_reason or "",
    )
    return refreshed


def _continue_prompt_for_contract(contract: CoordinatorStateContract) -> str:
    if contract.coordinator_mode == "worker_delegation":
        return render_prompt("research.coordinator.continue_worker_delegation")
    return render_prompt("research.coordinator.continue")


async def _publish_coordinator_run_state(
    session_id: str,
    *,
    contract: CoordinatorStateContract,
    run_status: str,
    run_completion_reason: str,
) -> None:
    await session_stream_manager.publish(
        session_id,
        "run_state",
        {
            "runStatus": str(run_status or "").strip().lower(),
            "runCompletionReason": str(run_completion_reason or "").strip().lower(),
            "notificationScope": "coordinator",
            "rootSessionId": contract.root_session_id,
            "coordinatorMode": contract.coordinator_mode,
        },
    )


__all__ = ["apply_coordinator_control"]
