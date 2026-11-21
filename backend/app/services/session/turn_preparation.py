"""Pure turn preparation decisions shared by both entry paths (refusals are ``TurnRefusedError``)."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from ...models import Project, User
from ...models import Session as AgentSession
from ..access_control import WORKSPACE_NOT_FOUND_MESSAGE
from ..admin.governance.admin_access_service import is_global_admin
from ..project import get_user_project_ids
from ..secure_work.coding.verification_contract import is_governed_coding_contract
from .turn_refusals import TurnRefusalState, TurnRefusedError

VALID_THINKING_LEVELS = frozenset({"off", "light", "deep"})


@dataclass(frozen=True, slots=True)
class RuntimeSelection:
    runtime_target_id: str
    runtime_label: str
    reason: str


def resolve_initial_runtime_selection(
    *,
    runtime_target_id: str,
    runtime_label_by_id: Mapping[str, str],
    runtime_target_id_explicit: bool,
) -> RuntimeSelection:
    """Resolve the caller's initial runtime choice before policy enforcement."""

    automatic_label = runtime_label_by_id.get("", "Automatic fallback chain")
    requested_runtime_target_id = str(runtime_target_id or "").strip()
    if not requested_runtime_target_id:
        return RuntimeSelection(runtime_target_id="", runtime_label=automatic_label, reason="automatic")

    if requested_runtime_target_id in runtime_label_by_id:
        return RuntimeSelection(
            runtime_target_id=requested_runtime_target_id,
            runtime_label=runtime_label_by_id[requested_runtime_target_id],
            reason="requested",
        )

    if runtime_target_id_explicit:
        raise TurnRefusedError(TurnRefusalState.RUNTIME_TARGET_INVALID, "Runtime target not found")

    return RuntimeSelection(
        runtime_target_id="",
        runtime_label=automatic_label,
        reason="implicit_unknown_runtime_fallback",
    )


def resolve_thinking_level(thinking_level: str) -> str:
    clean_level = str(thinking_level or "").strip()
    return clean_level if clean_level in VALID_THINKING_LEVELS else "light"


async def resolve_required_project_scope(
    db: AsyncSession,
    *,
    user: User,
    project_id: str,
    session: AgentSession | None,
) -> str:
    requested_project_id = str(project_id or "").strip()
    if requested_project_id:
        # Resolved before anything is written: a platform admin has a role in every Workspace that exists, so an
        # unknown ID would otherwise reach the session row.
        if await db.get(Project, requested_project_id) is None:
            raise TurnRefusedError(TurnRefusalState.PROJECT_NOT_FOUND, WORKSPACE_NOT_FOUND_MESSAGE)
        return requested_project_id

    session_project_id = str(session.project_id or "").strip() if session and session.project_id else ""
    if session_project_id:
        return session_project_id

    if await is_global_admin(db, user.id):
        return ""

    accessible_project_ids = await get_user_project_ids(user.id, db)
    if len(accessible_project_ids) == 1:
        return accessible_project_ids[0]
    if not accessible_project_ids:
        raise TurnRefusedError(TurnRefusalState.PROJECT_NOT_ASSIGNED, "No project is assigned to this user")
    raise TurnRefusedError(TurnRefusalState.PROJECT_SELECTION_REQUIRED, "Project selection is required")


def preserve_waiting_session_contract(
    *,
    session: AgentSession | None,
    agent_id: str,
    agent_type_explicit: bool,
    routing_intent: str,
    routing_reason: str,
    execution_strategy: str,
    execution_strategy_reason: str,
    expected_workflow_id: str,
    effective_agent_type: str,
) -> tuple[str, str, str, str, str, str]:
    """Keep the active workflow stable while a parent waits for sub-agent results."""

    current = (
        routing_intent,
        routing_reason,
        execution_strategy,
        execution_strategy_reason,
        expected_workflow_id,
        effective_agent_type,
    )
    if session is None:
        return current
    if agent_type_explicit or str(agent_id or "").strip():
        return current
    metadata = dict(session.metadata_ or {})
    awaiting_subagents = str(session.status or "").strip().lower() == "awaiting_subagents"
    # Governed coding sessions keep their routing for follow-up operator turns
    # (deliver, retry, clarify): re-routing the turn text has hijacked runs
    # into knowledge/aws-lookup workflows and blocked them at the execution
    # gate while an approved contract was active.
    governed_coding = is_governed_coding_contract(metadata.get("workflow_contract"))
    if not awaiting_subagents and not governed_coding:
        return current
    return (
        str(metadata.get("routing_intent") or "").strip() or routing_intent,
        str(metadata.get("routing_reason") or "").strip() or routing_reason,
        str(metadata.get("execution_strategy") or "").strip() or execution_strategy,
        str(metadata.get("execution_strategy_reason") or "").strip() or execution_strategy_reason,
        str(metadata.get("expected_workflow_id") or "").strip() or expected_workflow_id,
        str(session.agent_type or "").strip() or effective_agent_type,
    )


def clear_stale_workflow_metadata(metadata: dict, *, expected_workflow_id: str) -> None:
    workflow_contract = metadata.get("workflow_contract")
    # A governed coding contract (approved plan + verification contract) is
    # the session's mandate: per-turn routing must never displace it.
    # A follow-up delivery instruction routed as knowledge_request would
    # replace the contract mid-run, strip the delivery tools and turn the turn
    # into knowledge salvage.
    if is_governed_coding_contract(workflow_contract):
        return
    if expected_workflow_id:
        if isinstance(workflow_contract, dict):
            workflow_id = str(workflow_contract.get("workflow_id") or "").strip()
            if workflow_id and workflow_id != expected_workflow_id:
                metadata.pop("workflow_contract", None)
        return
    metadata.pop("workflow_contract", None)
    metadata.pop("current_sub_agent_group_id", None)
    metadata.pop("sub_agent_group_id", None)



__all__ = [
    "RuntimeSelection",
    "clear_stale_workflow_metadata",
    "preserve_waiting_session_contract",
    "resolve_initial_runtime_selection",
    "resolve_required_project_scope",
    "resolve_thinking_level",
]
