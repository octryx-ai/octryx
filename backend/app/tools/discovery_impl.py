"""Runtime implementations for lazy tool discovery tools."""

from __future__ import annotations

from typing import Any

from ..services.prompt_catalog.tool_descriptions import catalog_tool_description, catalog_tool_descriptions
from .context import ToolContext
from .definitions import get_all_definitions, get_tool_definition_metadata, is_tool_definition_available_for_agent_type
from .visibility import blocked_inactive_connector_tool_result, tool_visibility_decision


def _tokenize(text: str) -> list[str]:
    import re
    return re.findall(r"[a-zA-Z_][a-zA-Z0-9_]*", str(text or "").lower())


async def execute_tool_search(params: dict, context: ToolContext) -> dict[str, Any]:
    """Search discoverable (long-tail) tools and return compact metadata."""
    query = str(params.get("query", "")).strip()
    limit = max(1, min(int(params.get("limit", 10) or 10), 50))
    source_filter = str(params.get("source", "")).strip().lower() or None
    risk_filter = str(params.get("risk", "")).strip().lower() or None

    all_defs = get_all_definitions()
    # Core tools are always on, so they are never "discoverable" long-tail
    # results; the `metadata.is_core` check below already excludes them.
    core_names: list[str] = []

    agent_type = str(getattr(context, "capability_type", "diagnosis") if context else "diagnosis")

    query_terms = set(_tokenize(query)) if query else set()

    results: list[dict[str, Any]] = []
    for tool_name, definition in all_defs.items():
        if tool_name in core_names:
            continue
        if not is_tool_definition_available_for_agent_type(tool_name, agent_type):
            continue

        metadata = get_tool_definition_metadata(tool_name)
        if metadata.is_core:
            continue
        visibility = tool_visibility_decision(tool_name, context.project_config if context else None)
        if not visibility.visible:
            continue

        source = metadata.source
        if source_filter and source != source_filter:
            continue

        desc = str(definition.get("function", {}).get("description", "")).lower()

        if query_terms:
            name_terms = set(_tokenize(tool_name))
            desc_terms = set(_tokenize(desc))
            if not query_terms.intersection(name_terms | desc_terms):
                continue

        risk = metadata.risk
        if risk_filter and risk != risk_filter:
            continue

        results.append({
            "name": tool_name,
            # The served description (prompt catalog), as the tool schema would carry it.
            "summary": catalog_tool_description(
                tool_name, str(definition.get("function", {}).get("description", ""))
            )[:200],
            "source": source,
            "risk": risk,
            "owner_type": metadata.owner_type,
            "connector": metadata.connector,
            "required_config": metadata.required_config,
            "scopes": list(metadata.scopes),
            "mutates_state": metadata.mutates_state,
            "filesystem_access": metadata.filesystem_access,
            "network_access": metadata.network_access,
            "audit_required": metadata.audit_required,
            "approval_required": metadata.approval_required,
            "visibility": visibility.to_dict(),
        })

        if len(results) >= limit:
            break

    return {
        "tools": results,
        "count": len(results),
        "query": query,
    }


async def execute_tool_schema_get(params: dict, context: ToolContext) -> dict[str, Any]:
    """Load the full callable schema for a single tool if policy allows."""
    tool_name = str(params.get("tool_name", "")).strip()

    if not tool_name:
        return {"error": "tool_name is required"}

    all_defs = get_all_definitions()
    definition = all_defs.get(tool_name)

    if not definition:
        return {"error": f"Tool not found: {tool_name}"}

    agent_type = str(getattr(context, "capability_type", "diagnosis") if context else "diagnosis")
    if not is_tool_definition_available_for_agent_type(tool_name, agent_type):
        return {"error": f"Tool not available for this agent type: {tool_name}"}

    metadata = get_tool_definition_metadata(tool_name)
    blocked = blocked_inactive_connector_tool_result(tool_name, context.project_config if context else None)
    if blocked is not None:
        return blocked

    if metadata.is_core:
        return {"warning": f"Tool '{tool_name}' is a core tool and already available directly", "schema": definition}

    risk = metadata.risk
    if risk == "admin":
        return {"error": f"Tool '{tool_name}' requires admin privileges to execute"}
    if risk == "unknown":
        return {"error": f"Tool '{tool_name}' requires explicit governance metadata before schema exposure"}

    # Activate the tool for this run: the per-iteration tool surface includes
    # activated names, so the model can natively call it on the next step
    # (approach A / lazy tool discovery). Execution still passes the normal
    # governance/approval gates at dispatch.
    if context is not None:
        try:
            context.discovered_tool_names.add(tool_name)
        except AttributeError:
            pass

    return {
        "schema": catalog_tool_descriptions([definition])[0],
        "tool_name": tool_name,
        "activated": True,
        "metadata": {
            "source": metadata.source,
            "risk": metadata.risk,
            "owner_type": metadata.owner_type,
            "connector": metadata.connector,
            "required_config": metadata.required_config,
            "scopes": list(metadata.scopes),
            "mutates_state": metadata.mutates_state,
            "filesystem_access": metadata.filesystem_access,
            "network_access": metadata.network_access,
            "audit_required": metadata.audit_required,
            "approval_required": metadata.approval_required,
        },
    }
