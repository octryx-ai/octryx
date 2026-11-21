"""Trace-only session tool catalog construction."""

from __future__ import annotations

from collections import Counter
from typing import Any

from ...tools.base import get_tool_capability_snapshot
from ...tools.definitions import get_tool_definition_metadata
from ...tools.registry import TOOL_REGISTRY

MAX_CATALOG_ENTRIES_FOR_TRACE = 80
MAX_SCOPE_ITEMS_FOR_TRACE = 16
MAX_POLICY_TOOLS_FOR_TRACE = 40

_HIGH_RISK_NAME_PARTS = (
    "delete",
    "remove",
    "update",
    "create",
    "write",
    "apply",
    "commit",
    "merge",
    "rollback",
    "upgrade",
    "invoke",
    "action",
)
_APPROVAL_DESCRIPTION_PARTS = ("approval", "approve", "requires approval", "pending approval")


def _tool_name_from_definition(definition: dict[str, Any]) -> str:
    function = definition.get("function") if isinstance(definition, dict) else None
    if not isinstance(function, dict):
        return ""
    return str(function.get("name") or "").strip()


def _unique_string_list(value: Any, *, limit: int | None = None) -> list[str]:
    if not isinstance(value, list | tuple | set):
        return []
    seen: set[str] = set()
    items: list[str] = []
    for raw_item in value:
        item = str(raw_item or "").strip()
        if not item or item in seen:
            continue
        items.append(item)
        seen.add(item)
        if limit is not None and len(items) >= limit:
            break
    return items


def _tool_description(definition: dict[str, Any]) -> str:
    function = definition.get("function") if isinstance(definition, dict) else None
    if not isinstance(function, dict):
        return ""
    return str(function.get("description") or "").strip()


def _category_for_tool(name: str) -> str:
    lowered = name.lower()
    if lowered.startswith("run_flow_"):
        return "workflow"
    if lowered.startswith("aws_") or "_aws_" in lowered or "bedrock" in lowered:
        return "cloud/aws"
    if "kubernetes" in lowered or "k8s" in lowered or "kubectl" in lowered:
        return "cloud/kubernetes"
    if lowered.startswith(("jira_", "list_jira", "get_jira", "create_jira", "update_jira")):
        return "delivery/jira"
    if "confluence" in lowered:
        return "knowledge/confluence"
    if lowered.startswith("knowledge_") or lowered.endswith("_knowledge") or "knowledge" in lowered:
        return "knowledge"
    if "github" in lowered:
        return "scm/github"
    if "bitbucket" in lowered:
        return "scm/bitbucket"
    if lowered.startswith("git_") or lowered.startswith("worktree_"):
        return "scm/git"
    if "diagram" in lowered or "shape_library" in lowered:
        return "diagram"
    if "workspace" in lowered or lowered in {"bash", "run_cli_command", "list_directory", "read_workspace_file"}:
        return "workspace"
    if "mcp" in lowered:
        return "mcp"
    if "office" in lowered or "presentation" in lowered or "word" in lowered or "excel" in lowered:
        return "office"
    if lowered.startswith("admin_"):
        return "admin"
    if "tool_search" in lowered or "schema" in lowered:
        return "discovery"
    return "general"


def _approval_hint(name: str, description: str) -> bool:
    haystack = f"{name} {description}".lower()
    return any(part in haystack for part in _APPROVAL_DESCRIPTION_PARTS)


def _risk_level(*, name: str, description: str, read_only: bool, change_only: bool, approval_hint: bool) -> str:
    lowered_name = name.lower()
    if approval_hint or any(part in lowered_name for part in _HIGH_RISK_NAME_PARTS):
        return "high"
    if change_only or not read_only:
        return "medium"
    if "secret" in description.lower():
        return "medium"
    return "low"


def _availability_reason(
    *,
    workflow_contract: dict[str, Any] | None,
    request_analysis: dict[str, Any] | None,
) -> str:
    workflow_id = str((workflow_contract or {}).get("workflow_id") or "").strip()
    if workflow_id:
        return f"workflow:{workflow_id}"
    route_reason = str((request_analysis or {}).get("route_reason") or "").strip()
    if route_reason:
        return f"request_analysis:{route_reason}"
    return "current_turn_tool_resolution"


def _routing_policy_catalog_metadata(request_analysis: dict[str, Any] | None) -> dict[str, Any]:
    analysis = request_analysis if isinstance(request_analysis, dict) else {}
    resolution = (
        analysis.get("workflow_routing_policy_resolution")
        if isinstance(analysis.get("workflow_routing_policy_resolution"), dict)
        else {}
    )
    tool_policy = resolution.get("tool_policy") if isinstance(resolution.get("tool_policy"), dict) else {}
    allowlist = _unique_string_list(tool_policy.get("allowlist"))
    denylist = _unique_string_list(tool_policy.get("denylist"))
    is_db_policy = bool(resolution.get("source") == "db" and resolution.get("status") == "matched")
    is_policy_shaped = is_db_policy
    policy_source = "workflow_routing_policy" if is_db_policy else "no_workflow_routing_policy"
    return {
        "policy_source": policy_source,
        "routing_policy_id": resolution.get("policy_id") if is_db_policy else None,
        "routing_policy_version_id": resolution.get("policy_version_id") if is_db_policy else None,
        "routing_policy_matched_group_id": resolution.get("matched_group_id") if is_db_policy else None,
        "policy_allowlist_count": len(allowlist) if is_policy_shaped else 0,
        "policy_denylist_count": len(denylist) if is_policy_shaped else 0,
        "policy_allowlist": allowlist[:MAX_POLICY_TOOLS_FOR_TRACE] if is_policy_shaped else [],
        "policy_denylist": denylist[:MAX_POLICY_TOOLS_FOR_TRACE] if is_policy_shaped else [],
        "omitted_policy_allowlist_count": max(0, len(allowlist) - MAX_POLICY_TOOLS_FOR_TRACE)
        if is_policy_shaped
        else 0,
        "omitted_policy_denylist_count": max(0, len(denylist) - MAX_POLICY_TOOLS_FOR_TRACE)
        if is_policy_shaped
        else 0,
    }


def _session_scope_metadata(tool_context: Any | None) -> dict[str, Any]:
    if tool_context is None:
        return {"scope_source": "unavailable"}
    project_ids = _unique_string_list(getattr(tool_context, "project_ids", None), limit=MAX_SCOPE_ITEMS_FOR_TRACE)
    all_project_ids = _unique_string_list(getattr(tool_context, "project_ids", None))
    roles = _unique_string_list(getattr(tool_context, "roles", None), limit=MAX_SCOPE_ITEMS_FOR_TRACE)
    all_roles = _unique_string_list(getattr(tool_context, "roles", None))
    return {
        "scope_source": "tool_context",
        "session_id": str(getattr(tool_context, "session_id", "") or "").strip() or None,
        "user_id": str(getattr(tool_context, "user_id", "") or "").strip() or None,
        "project_ids": project_ids,
        "omitted_project_id_count": max(0, len(all_project_ids) - len(project_ids)),
        "roles": roles,
        "omitted_role_count": max(0, len(all_roles) - len(roles)),
    }


def _policy_effect_metadata(
    *,
    entries: list[dict[str, Any]],
    policy_metadata: dict[str, Any],
) -> dict[str, Any]:
    if policy_metadata.get("policy_source") != "workflow_routing_policy":
        return {
            "denied_tools": [],
            "skipped_policy_tools": [],
            "unavailable_policy_tools": [],
            "omitted_policy_effect_count": 0,
        }
    available_names = {
        str(entry.get("name") or "").strip()
        for entry in entries
        if str(entry.get("name") or "").strip()
    }
    allowlist = _unique_string_list(policy_metadata.get("policy_allowlist"))
    denylist = _unique_string_list(policy_metadata.get("policy_denylist"))
    denied_tools = sorted(name for name in denylist if name)
    skipped_policy_tools = sorted(name for name in allowlist if name in denylist)
    unavailable_policy_tools = sorted(
        name for name in allowlist if name not in available_names and name not in denylist
    )
    combined_count = len(denied_tools) + len(skipped_policy_tools) + len(unavailable_policy_tools)
    return {
        "denied_tools": denied_tools[:MAX_POLICY_TOOLS_FOR_TRACE],
        "skipped_policy_tools": skipped_policy_tools[:MAX_POLICY_TOOLS_FOR_TRACE],
        "unavailable_policy_tools": unavailable_policy_tools[:MAX_POLICY_TOOLS_FOR_TRACE],
        "omitted_policy_effect_count": max(0, combined_count - (MAX_POLICY_TOOLS_FOR_TRACE * 3)),
    }


def _catalog_entry(
    definition: dict[str, Any],
    *,
    availability_reason: str,
) -> dict[str, Any] | None:
    name = _tool_name_from_definition(definition)
    if not name:
        return None
    description = _tool_description(definition)
    metadata = get_tool_definition_metadata(name)
    tool = TOOL_REGISTRY.get(name)
    capability = get_tool_capability_snapshot(tool) if tool is not None else None
    read_only = bool(capability.is_read_only) if capability is not None else not metadata.change_only
    approval_required = _approval_hint(name, description)
    risk_level = _risk_level(
        name=name,
        description=description,
        read_only=read_only,
        change_only=metadata.change_only,
        approval_hint=approval_required,
    )
    return {
        "name": name,
        "category": _category_for_tool(name),
        "risk_level": risk_level,
        "read_only": read_only,
        "approval_hint": approval_required,
        "core": metadata.is_core,
        "plan_excluded": metadata.plan_excluded,
        "availability_reason": availability_reason,
        "description": description[:220],
    }


def build_session_tool_catalog(
    *,
    tool_definitions: list[dict[str, Any]],
    capability_type: str,
    request_analysis: dict[str, Any] | None,
    workflow_contract: dict[str, Any] | None,
    tool_context: Any | None = None,
) -> dict[str, Any]:
    """Build a compact session-aware catalog from already-resolved tool definitions.

    This function intentionally does not broaden or execute tools. It describes
    the catalog that existing runtime preparation already produced and records
    the session/policy context that shaped it.
    """

    reason = _availability_reason(workflow_contract=workflow_contract, request_analysis=request_analysis)
    entries = [
        entry
        for definition in tool_definitions or []
        if isinstance(definition, dict)
        if (entry := _catalog_entry(definition, availability_reason=reason)) is not None
    ]
    entries.sort(key=lambda item: str(item.get("name") or ""))
    category_counts = Counter(str(item["category"]) for item in entries)
    risk_counts = Counter(str(item["risk_level"]) for item in entries)
    approval_required_count = sum(1 for item in entries if item.get("approval_hint"))
    omitted_count = max(0, len(entries) - MAX_CATALOG_ENTRIES_FOR_TRACE)
    policy_metadata = _routing_policy_catalog_metadata(request_analysis)
    policy_effect_metadata = _policy_effect_metadata(entries=entries, policy_metadata=policy_metadata)
    return {
        "version": 2,
        "mode": "trace_only",
        "contract_kind": "session_aware_tool_catalog",
        "contract_version": 2,
        "capability_type": capability_type,
        "availability_reason": reason,
        "session_scope": _session_scope_metadata(tool_context),
        **policy_metadata,
        **policy_effect_metadata,
        "tool_count": len(entries),
        "category_counts": dict(sorted(category_counts.items())),
        "risk_counts": dict(sorted(risk_counts.items())),
        "approval_hint_count": approval_required_count,
        "omitted_entry_count": omitted_count,
        "entries": entries[:MAX_CATALOG_ENTRIES_FOR_TRACE],
    }


__all__ = ["build_session_tool_catalog"]
