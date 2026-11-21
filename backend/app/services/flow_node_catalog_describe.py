"""Labels, schemas and risk descriptions of the Flow Builder catalog items.

Pure helpers of :mod:`app.services.flow_node_catalog`.
"""

from __future__ import annotations

from typing import Any

from ..tools.registry import TOOL_REGISTRY
from .circuit_breaker import infer_connector_name
from .tool_config import get_default_connector_for_tool


def _connector_for_tool(tool_name: str) -> str | None:
    return get_default_connector_for_tool(tool_name) or infer_connector_name(tool_name)


def _node_type_for_tool(tool_name: str, category: str) -> str:
    if tool_name.startswith("knowledge_") or "knowledge" in category.lower():
        return "retrieval"
    if any(marker in tool_name for marker in ("search_", "list_", "get_", "read_")):
        return "retrieval"
    return "tool_step"


def _tool_category(tool_name: str, connector_name: str | None) -> str:
    if connector_name:
        return f"Tools / {connector_name.title()}"
    if tool_name.startswith("knowledge_"):
        return "Knowledge"
    if tool_name.startswith(("skill_", "instruction_get")):
        return "Agent Context"
    if tool_name.startswith(("read_", "search_workspace", "list_directory")):
        return "Workspace"
    if tool_name.startswith(("admin_", "list_admin", "get_admin")):
        return "Administration"
    return "Tools / Core"


def _display_name(tool_name: str) -> str:
    return tool_name.replace("_", " ").title()


def _tool_description(definition: dict[str, Any], tool_name: str) -> str:
    function = definition.get("function") if isinstance(definition, dict) else {}
    description = function.get("description") if isinstance(function, dict) else None
    return str(description or TOOL_REGISTRY[tool_name].description or "")


def _tool_config_schema(tool_name: str, definition: dict[str, Any]) -> dict[str, Any]:
    function = definition.get("function") if isinstance(definition, dict) else {}
    parameters = function.get("parameters") if isinstance(function, dict) else {}
    return {
        "type": "object",
        "properties": {
            "tool": {"type": "string", "const": tool_name},
            "arguments": parameters if isinstance(parameters, dict) else {"type": "object"},
        },
        "required": ["tool"],
        "additionalProperties": True,
    }


def _tool_permission_requirements(tool_name: str, *, connector_name: str | None, read_only: bool) -> list[str]:
    requirements = ["Project tool visibility must allow this tool at execution time."]
    if connector_name:
        requirements.append(f"{connector_name} connector credentials and project grant must be active.")
    if not read_only:
        requirements.append("Mutating or change-capable tools may require approval policy before execution.")
    if tool_name.startswith("mcp__"):
        requirements.append("MCP server and tool permission must be rechecked at runtime.")
    return requirements


def _tool_cost_risk(tool_name: str, *, read_only: bool) -> str:
    if not read_only:
        return "high"
    if tool_name.startswith(("knowledge_", "search_", "list_", "get_", "read_")):
        return "low"
    return "medium"


def _tool_evidence_behavior(tool_name: str, category: str) -> str:
    normalized = f"{tool_name} {category}".lower()
    if "knowledge" in normalized:
        return "Returns project-scoped Knowledge evidence and should cite source keys or known gaps."
    if any(marker in normalized for marker in ("jira", "confluence", "bitbucket", "github")):
        return "Returns connector evidence that must be cited with source identifiers and timestamps when available."
    if any(marker in normalized for marker in ("aws", "kubernetes", "grafana", "prometheus", "loki")):
        return "Returns operational evidence; answers should distinguish observed facts from inference."
    return "May provide evidence for downstream analysis; outputs should remain traceable in the run."


def _generic_cost_risk(contract: dict[str, Any]) -> str:
    if contract.get("calls_llm"):
        return "medium"
    if contract.get("calls_tools"):
        return "medium"
    return "low"


def _generic_evidence_behavior(contract: dict[str, Any]) -> str:
    if contract.get("calls_tools"):
        return "Evidence depends on bound tool or retrieval configuration."
    if contract.get("type") == "evaluation":
        return "Evaluates candidate output against configured quality or evidence gates."
    return "Does not fetch evidence by itself."


def _generic_audit_behavior(contract: dict[str, Any]) -> str:
    if contract.get("can_pause"):
        return "Pause and human decision state must be stored with user identity."
    return "Node execution state is traceable through the flow run audit trail."
