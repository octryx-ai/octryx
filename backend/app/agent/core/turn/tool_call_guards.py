"""Per-call tool guards: the exec-policy guard chain and the custom guard audit trail."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.tools.context import ToolContext

from ....services.exec_policy import get_effective_exec_policy_config
from ....services.exec_policy.guard_audit import audit_custom_tool_guard_decision
from ....services.request_context import get_current_request_id
from ....services.turn_tool_guards import (
    clarification_gate_guard_result as _clarification_gate_guard_result,
)
from ....services.turn_tool_guards import (
    coding_intelligence_guard_result as _coding_intelligence_guard_result,
)
from ....services.turn_tool_guards import (
    custom_exec_policy_tool_guard_decisions as _custom_exec_policy_tool_guard_decisions,
)
from ....services.turn_tool_guards import (
    custom_exec_policy_tool_guard_result as _custom_exec_policy_tool_guard_result,
)
from ....services.turn_tool_guards_aws import (
    aws_topology_snapshot_duplicate_guard_result as _aws_topology_snapshot_duplicate_guard_result,
)
from ....services.turn_tool_guards_code_structure import (
    code_structure_diagram_evidence_guard_result as _code_structure_diagram_evidence_guard_result,
)
from ....services.turn_tool_guards_research import technical_source_guard_result as _technical_source_guard_result


def _aws_guard_result(
    *,
    tool_name: str,
    tool_args: dict[str, Any],
    turn_tool_history: list[dict[str, Any]] | None,
    context_snapshot: dict[str, Any] | None,
    exec_policy_config: dict[str, Any] | None,
) -> dict[str, Any] | None:
    return _aws_topology_snapshot_duplicate_guard_result(
        tool_name=tool_name,
        tool_args=tool_args,
        turn_tool_history=turn_tool_history,
        exec_policy_config=exec_policy_config,
    )


def _evidence_guard_result(
    *,
    tool_name: str,
    tool_args: dict[str, Any],
    turn_tool_history: list[dict[str, Any]] | None,
    context_snapshot: dict[str, Any] | None,
    exec_policy_config: dict[str, Any] | None,
) -> dict[str, Any] | None:
    code_structure_guard = _code_structure_diagram_evidence_guard_result(
        tool_name=tool_name,
        tool_args=tool_args,
        turn_tool_history=turn_tool_history,
        context_snapshot=context_snapshot,
        exec_policy_config=exec_policy_config,
    )
    if code_structure_guard is not None:
        return code_structure_guard
    clarification_guard = _clarification_gate_guard_result(
        tool_name=tool_name,
        tool_args=tool_args,
        context_snapshot=context_snapshot,
        exec_policy_config=exec_policy_config,
    )
    if clarification_guard is not None:
        return clarification_guard
    return _technical_source_guard_result(
        tool_name=tool_name,
        tool_args=tool_args,
        context_snapshot=context_snapshot,
        exec_policy_config=exec_policy_config,
    )


def tool_execution_guard_result(
    *,
    tool_name: str,
    tool_args: dict[str, Any],
    turn_tool_history: list[dict[str, Any]] | None,
    capability_type: str | None,
    context_snapshot: dict[str, Any] | None,
    exec_policy_config: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """The first guard refusal for this call, in fixed order, or ``None`` when every guard lets it pass."""
    custom_guard = _custom_exec_policy_tool_guard_result(
        tool_name=tool_name,
        tool_args=tool_args,
        capability_type=capability_type,
        exec_policy_config=exec_policy_config,
    )
    if custom_guard is not None:
        return custom_guard
    shared = {
        "tool_name": tool_name,
        "tool_args": tool_args,
        "turn_tool_history": turn_tool_history,
        "context_snapshot": context_snapshot,
        "exec_policy_config": exec_policy_config,
    }
    aws_guard = _aws_guard_result(**shared)
    if aws_guard is not None:
        return aws_guard
    evidence_guard = _evidence_guard_result(**shared)
    if evidence_guard is not None:
        return evidence_guard
    return _coding_intelligence_guard_result(
        tool_name=tool_name,
        tool_args=tool_args,
        turn_tool_history=turn_tool_history,
        capability_type=capability_type,
        exec_policy_config=exec_policy_config,
    )


async def alert_scoped(tool_context: ToolContext) -> bool:
    """True while the session's workflow run has an alert scope: its tools check the target on every call."""
    from ....tools.alert_scope import run_alert_scope

    return await run_alert_scope(tool_context) is not None


async def _load_exec_policy_config(db: AsyncSession, tool_context: ToolContext) -> dict[str, Any]:
    project_id = next(
        (str(project_id).strip() for project_id in tool_context.project_ids if str(project_id).strip()), None
    )
    return await get_effective_exec_policy_config(db, project_id=project_id)


async def load_and_audit_custom_tool_guards(
    db: AsyncSession,
    *,
    tool_context: ToolContext,
    assistant_message_id: str,
    tool_call_id: str,
    tool_name: str,
    tool_args: dict[str, Any],
    persistable_tool_args: dict[str, Any],
    context_snapshot: dict[str, Any],
) -> dict[str, Any]:
    """Load the effective exec policy, expose its guard rules to the turn, and audit every custom guard decision."""
    exec_policy_config = await _load_exec_policy_config(db, tool_context)
    context_snapshot["exec_policy_agent_guard_rules"] = exec_policy_config.get("agent_guard_rules") or []
    context_snapshot["exec_policy_custom_tool_guard_rules"] = exec_policy_config.get("custom_tool_guard_rules") or []
    custom_guard_decisions = _custom_exec_policy_tool_guard_decisions(
        tool_name=tool_name,
        tool_args=tool_args,
        capability_type=tool_context.capability_type,
        exec_policy_config=exec_policy_config,
    )
    for decision in custom_guard_decisions:
        await audit_custom_tool_guard_decision(
            db,
            user_id=tool_context.user_id,
            session_id=tool_context.session_id,
            message_id=assistant_message_id,
            tool_call_id=tool_call_id,
            request_id=tool_context.request_id or get_current_request_id(),
            tool_name=tool_name,
            tool_args=persistable_tool_args,
            capability_type=tool_context.capability_type,
            decision=decision,
        )
    return exec_policy_config
