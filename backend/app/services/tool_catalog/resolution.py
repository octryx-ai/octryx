"""Session tool catalog resolver lifecycle contracts."""

from __future__ import annotations

from typing import Any

from .session_catalog import build_session_tool_catalog

MAX_RESOLUTION_TOOLS = 40


def _tool_name_from_definition(definition: dict[str, Any]) -> str:
    function = definition.get("function") if isinstance(definition, dict) else None
    if not isinstance(function, dict):
        return ""
    return str(function.get("name") or "").strip()


def _compact_tool_names(tool_definitions: list[dict[str, Any]]) -> tuple[list[str], int]:
    names = sorted(
        {
            name
            for definition in tool_definitions or []
            if isinstance(definition, dict)
            if (name := _tool_name_from_definition(definition))
        }
    )
    return names[:MAX_RESOLUTION_TOOLS], max(0, len(names) - MAX_RESOLUTION_TOOLS)


def _lifecycle_event(phase: str, status: str, detail: str, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
    event: dict[str, Any] = {
        "phase": phase,
        "status": status,
        "detail": detail,
    }
    clean_metadata = {key: value for key, value in (metadata or {}).items() if value not in (None, "", [], {}, ())}
    if clean_metadata:
        event["metadata"] = clean_metadata
    return event


def _build_lifecycle_events(catalog: dict[str, Any], tool_definitions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    visible_names, omitted_names = _compact_tool_names(tool_definitions)
    policy_source = str(catalog.get("policy_source") or "no_workflow_routing_policy")
    scope = catalog.get("session_scope") if isinstance(catalog.get("session_scope"), dict) else {}
    return [
        _lifecycle_event(
            "scope",
            "ok" if scope.get("scope_source") == "tool_context" else "info",
            "Resolved bounded session scope for catalog tracing.",
            {
                "scope_source": scope.get("scope_source"),
                "project_count": len(scope.get("project_ids") or []),
                "role_count": len(scope.get("roles") or []),
            },
        ),
        _lifecycle_event(
            "policy",
            "ok"
            if policy_source == "workflow_routing_policy"
            else "info",
            "Applied already-resolved runtime routing policy metadata to the catalog contract.",
            {
                "policy_source": policy_source,
                "routing_policy_id": catalog.get("routing_policy_id"),
                "routing_policy_version_id": catalog.get("routing_policy_version_id"),
                "allowlist_count": catalog.get("policy_allowlist_count"),
                "denylist_count": catalog.get("policy_denylist_count"),
            },
        ),
        _lifecycle_event(
            "catalog",
            "ok" if catalog.get("tool_count") else "info",
            "Built compact catalog over the runtime-resolved tool definitions.",
            {
                "tool_count": catalog.get("tool_count"),
                "visible_tools": visible_names,
                "omitted_tool_count": omitted_names,
                "category_counts": catalog.get("category_counts"),
                "risk_counts": catalog.get("risk_counts"),
            },
        ),
    ]


def resolve_session_tool_catalog(
    *,
    tool_definitions: list[dict[str, Any]],
    capability_type: str,
    request_analysis: dict[str, Any] | None,
    workflow_contract: dict[str, Any] | None,
    tool_context: Any | None = None,
) -> dict[str, Any]:
    """Resolve a first-class trace contract around the current turn catalog.

    The resolver is observational: it records the lifecycle around the
    already-resolved runtime tool definitions and returns the `catalog` payload
    the planner and the trace code read.
    """

    catalog = build_session_tool_catalog(
        tool_definitions=tool_definitions,
        capability_type=capability_type,
        request_analysis=request_analysis,
        workflow_contract=workflow_contract,
        tool_context=tool_context,
    )
    lifecycle = _build_lifecycle_events(catalog, tool_definitions)
    policy_effect_counts = {
        "denied": len(catalog.get("denied_tools") or []),
        "skipped": len(catalog.get("skipped_policy_tools") or []),
        "unavailable": len(catalog.get("unavailable_policy_tools") or []),
    }
    status = "empty" if not catalog.get("tool_count") else "resolved"
    return {
        "version": 1,
        "mode": "trace_only",
        "contract_kind": "session_tool_catalog_resolution",
        "status": status,
        "catalog": catalog,
        "decision_summary": {
            "capability_type": capability_type,
            "tool_count": catalog.get("tool_count") or 0,
            "catalog_contract_version": catalog.get("contract_version"),
            "scope_source": (catalog.get("session_scope") or {}).get("scope_source")
            if isinstance(catalog.get("session_scope"), dict)
            else "unavailable",
            "policy_source": catalog.get("policy_source"),
            "routing_policy_id": catalog.get("routing_policy_id"),
            "routing_policy_version_id": catalog.get("routing_policy_version_id"),
            "policy_effect_counts": policy_effect_counts,
            "approval_hint_count": catalog.get("approval_hint_count") or 0,
            "risk_counts": catalog.get("risk_counts") or {},
        },
        "lifecycle": lifecycle,
        "runtime_effect": "observational_only",
        "next_actions": [
            "planner_may_use_catalog_contract",
            "runtime_allow_deny_remains_existing_loop_behavior",
        ],
    }


__all__ = ["resolve_session_tool_catalog"]
