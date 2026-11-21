"""Timeline events of turn preparation: context, workflow selection and bound instructions."""

from __future__ import annotations

from typing import Any

from .timeline import append_decision_timeline_event, compact_items


def append_context_prepared_event(
    context_snapshot: dict[str, Any],
    *,
    capability_type: str,
    request_analysis: dict[str, Any] | None,
    workflow_contract: dict[str, Any] | None,
) -> dict[str, Any]:
    analysis = request_analysis if isinstance(request_analysis, dict) else {}
    contract = workflow_contract if isinstance(workflow_contract, dict) else {}
    workflow_id = str(contract.get("workflow_id") or "").strip()
    route_reason = str(contract.get("route_reason") or analysis.get("route_reason") or "").strip()
    requested_domains = analysis.get("requested_domains") if isinstance(analysis.get("requested_domains"), list) else []
    title = "Workflow context prepared" if workflow_id else "Request context prepared"
    detail = f"Matched workflow `{workflow_id}`." if workflow_id else "No workflow contract was matched for this turn."
    return append_decision_timeline_event(
        context_snapshot,
        phase="context",
        title=title,
        status="ok" if workflow_id else "info",
        detail=detail,
        metadata={
            "capability_type": capability_type,
            "workflow_id": workflow_id,
            "workflow_class": contract.get("workflow_class"),
            "workflow_contract_source": contract.get("workflow_contract_source"),
            "diagram_source": contract.get("diagram_source"),
            "diagram_detail": contract.get("diagram_detail"),
            "route_reason": route_reason,
            "requested_domains": requested_domains,
        },
    )


def append_workflow_routing_policy_event(
    context_snapshot: dict[str, Any],
    *,
    routing_resolution: dict[str, Any] | None,
) -> dict[str, Any]:
    resolution = routing_resolution if isinstance(routing_resolution, dict) else {}
    source = str(resolution.get("source") or "").strip()
    status = str(resolution.get("status") or "").strip()
    workflow_id = str(resolution.get("workflow_id") or "").strip()
    workflow_class = str(resolution.get("workflow_class") or "").strip()
    tool_policy = resolution.get("tool_policy") if isinstance(resolution.get("tool_policy"), dict) else {}
    allowed_tools = compact_items(
        [str(item) for item in tool_policy.get("allowlist") or [] if str(item).strip()]
    )[0]
    if source == "db" and status == "matched":
        title = "Workflow run phase selected"
        detail = f"The workflow run's phase selected workflow `{workflow_id}` / `{workflow_class}`."
        timeline_status = "ok"
    else:
        title = "No workflow selected"
        detail = str(resolution.get("unmatched_reason") or "No workflow governs this turn.")
        timeline_status = "warning"
    return append_decision_timeline_event(
        context_snapshot,
        phase="routing_policy",
        title=title,
        status=timeline_status,
        detail=detail,
        metadata={
            "source": source or "unknown",
            "status": status or "unknown",
            "workflow_id": workflow_id,
            "workflow_class": workflow_class,
            "policy_id": resolution.get("policy_id"),
            "policy_version_id": resolution.get("policy_version_id"),
            "matched_group_id": resolution.get("matched_group_id"),
            "allowed_tools": allowed_tools,
            "safety_constraints": resolution.get("safety_constraints"),
        },
    )


def append_instructions_event(
    context_snapshot: dict[str, Any],
    *,
    instructions: list[dict[str, Any]] | None,
) -> dict[str, Any]:
    """The instructions this turn read (A8): key@version per layer, never the bodies."""
    items = [item for item in instructions or [] if isinstance(item, dict)]
    keys, omitted = compact_items([f"{item.get('key')}@{item.get('version')}" for item in items], limit=12)
    return append_decision_timeline_event(
        context_snapshot,
        phase="instructions",
        title="Instructions loaded" if items else "No instruction bound",
        status="ok" if items else "info",
        detail=(
            f"{len(items)} instruction(s) bound by scope and workflow."
            if items else "No published instruction is bound to this turn's scope or workflow."
        ),
        metadata={
            "keys": keys,
            "omitted_key_count": omitted,
            "layers": sorted({str(item.get("layer") or "") for item in items}),
            "token_estimate": sum(int(item.get("token_estimate") or 0) for item in items),
        },
    )
