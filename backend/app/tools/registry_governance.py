"""The checks every tool call passes before it runs: capability, tool policy, approvals, the chat's writes."""

from typing import Any

from ..services.decisions.tool_dispatch import recorded_tool_dispatch
from ..services.tool_access_policy import blocked_tool_result, tool_project_policy_decision
from .context import ToolContext
from .results import annotate_tool_result_payload
from .visibility import blocked_inactive_connector_tool_result


def _chat_write_answers_explicit_allow(tool_name: str, context: ToolContext, decision: Any) -> bool:
    from ..services.run_capability.chat_writes import chat_connector_write_permitted
    from ..services.tool_access_policy_rules import HIGH_RISK_EXPLICIT_ALLOW_REASON

    return (not decision.allowed and decision.reason == HIGH_RISK_EXPLICIT_ALLOW_REASON
            and chat_connector_write_permitted(tool_name, context))


def _is_chat_connector_write(tool_name: str, context: ToolContext) -> bool:
    from ..services.run_capability.chat_writes import chat_connector_write_permitted

    return chat_connector_write_permitted(tool_name, context)


@recorded_tool_dispatch
async def _run_governed_tool_checks(tool_name: str, params: dict, context: ToolContext) -> dict | None:
    from ..services.workflow_runs.handoff.lifecycle import guard_tool_context
    from ..services.workflow_runs.records import WorkflowRunError

    try:
        await guard_tool_context(context)
    except WorkflowRunError as error:
        return {"status": "refused", "reason": error.code, "error": str(error)}
    # An agent set to No tools (text only) runs no tool at all, whatever the model or the platform asked for.
    from app.services.agent_tool_surface_decision import tool_surface_dispatch_refusal

    surface_refusal = tool_surface_dispatch_refusal(tool_name, context)
    if surface_refusal is not None:
        return surface_refusal
    # The published agent's tools deny refuses at dispatch too, not only in the model's view.
    from ..services.agent_tools_deny import agent_tools_deny_refusal

    deny_refusal = agent_tools_deny_refusal(tool_name, context)
    if deny_refusal is not None:
        return deny_refusal
    # A chat turn calls only what the person's work roles grant; named, never silent.
    from ..services.work_role_model.surfaces import dispatch_refusal

    role_refusal = dispatch_refusal(tool_name, context)
    if role_refusal is not None:
        return annotate_tool_result_payload(tool_name, role_refusal, category="denied_by_policy",
                                            reason=role_refusal.get("code"), policy=str(role_refusal["policy"]))
    blocked_by_visibility = blocked_inactive_connector_tool_result(tool_name, context.project_config)
    if blocked_by_visibility is None:
        # The classification level also judges the call's arguments (``run_kubectl logs``).
        from ..services.classification_tool_policy import classification_tool_refusal

        blocked_by_visibility = classification_tool_refusal(tool_name, context.project_config, params)
    if (blocked_by_visibility is not None and getattr(context, "workflow_platform_action", False)
            and blocked_by_visibility.get("code") in {"connection_agent_tools_read_only",
                                                      "connection_agent_tools_off"}):
        # The connection's agent tools level governs agents; a published workflow's own typed platform action is not
        # an agent tool call (otherwise scm.create_branch was refused on a "Tools: read" Bitbucket connection).
        blocked_by_visibility = None
    if blocked_by_visibility is not None:
        return annotate_tool_result_payload(
            tool_name,
            blocked_by_visibility,
            category="denied_by_policy",
            reason=blocked_by_visibility.get("reason"),
            policy=str(blocked_by_visibility.get("policy") or "connector_activation"),
        )
    policy_decision = tool_project_policy_decision(tool_name, context.project_config)
    if (not policy_decision.allowed and getattr(context, "workflow_platform_action", False)
            and policy_decision.reason == "high_risk_tool_requires_explicit_allow"):
        # A published workflow's own platform action is explicitly allowed by that workflow (otherwise Jira intake
        # could not post its questions by default). Project deny lists and deny patterns still refuse.
        policy_decision = None
    if policy_decision is not None and _chat_write_answers_explicit_allow(tool_name, context, policy_decision):
        policy_decision = None
    if policy_decision is not None and not policy_decision.allowed:
        return annotate_tool_result_payload(
            tool_name,
            blocked_tool_result(tool_name, policy_decision),
            category="denied_by_policy",
            reason=policy_decision.reason,
            policy=policy_decision.policy,
        )
    # The run capability refuses a tool that exceeds the run's class before any MCP or approval check.
    from ..services.run_capability.escalation import CAPABILITY_REFUSAL_POLICY, capability_dispatch_refusal

    capability_refusal = capability_dispatch_refusal(tool_name, context)
    if capability_refusal is not None:
        return annotate_tool_result_payload(
            tool_name, capability_refusal, category="denied_by_policy", policy=CAPABILITY_REFUSAL_POLICY
        )
    # Imported lazily: the approval gate's approval and notification imports must not run at module load.
    from ..services.mcp_capability_gate import evaluate_mcp_capability_dispatch
    from ..services.mcp_governance.resource_dispatch import (
        evaluate_mcp_resource_dispatch,
        finalize_mcp_resource_dispatch,
    )
    from ..services.tool_approval.gate import enforce_tool_approval

    # MCP governance sits between tool policy and approval: server activation
    # first, then the workspace capability binding, then approval carrying the
    # explicit capability subject instead of the generic bridge identity. Mirrored
    # tools and governed resources/prompts are disjoint tool sets with their own
    # catalogs, so at most one of the two gates ever resolves a subject.
    mcp_gate = await evaluate_mcp_capability_dispatch(tool_name, params, context)
    if mcp_gate.blocked_result is not None:
        return annotate_tool_result_payload(
            tool_name,
            mcp_gate.blocked_result,
            category="denied_by_policy",
            reason=mcp_gate.blocked_reason,
            policy=mcp_gate.blocked_policy,
        )
    resource_gate = await evaluate_mcp_resource_dispatch(tool_name, params, context)
    if resource_gate.blocked_result is not None:
        return annotate_tool_result_payload(
            tool_name,
            resource_gate.blocked_result,
            category="denied_by_policy",
            reason=resource_gate.blocked_reason,
            policy=resource_gate.blocked_policy,
        )
    if mcp_gate.approval_subject is None and resource_gate.approval_subject is None and _is_chat_connector_write(
            tool_name, context):
        from ..services.tool_approval.previews import chat_write_route_refusal

        # A chat write its connection plan refuses is answered now, never put to the person to confirm first.
        route_refusal = chat_write_route_refusal(tool_name, params, context.project_config)
        if route_refusal is not None:
            return annotate_tool_result_payload(tool_name, route_refusal, category="denied_by_policy",
                                                reason=route_refusal.get("code"), policy="connection_routing")
    approval_result = await enforce_tool_approval(
        tool_name,
        params,
        context,
        subject=mcp_gate.approval_subject or resource_gate.approval_subject,
    )
    from ..services.coding_dispatch_gates import enforce_coding_dispatch_gates

    # Delivery proof and upgrade gate order; the result arrives annotated with the refusing gate.
    delivery_block = (
        None if approval_result is not None else await enforce_coding_dispatch_gates(tool_name, params, context)
    )
    # The governed resource request is closed out once every gate has answered: a
    # hold or a later block is final and is audited here, while a request that
    # actually proceeds is only marked as already-governed, so the tool — not this
    # gate — records whether anything executed.
    await finalize_mcp_resource_dispatch(
        resource_gate,
        context,
        tool_name=tool_name,
        approval_held=approval_result is not None,
        blocked_downstream=delivery_block is not None,
    )
    if approval_result is not None and approval_result.get("next_tool"):
        # The chat's write plan does not cover this call: no one is asked, the model is told its next step.
        from ..services.run_capability.chat_write_plan import PLAN_POLICY

        return annotate_tool_result_payload(tool_name, approval_result, category="denied_by_policy",
                                            reason=approval_result.get("code"), policy=PLAN_POLICY)
    if approval_result is not None:
        return annotate_tool_result_payload(
            tool_name,
            approval_result,
            category="approval_required",
            policy="tool_approval_gate",
        )
    return delivery_block
