"""The catalog of published workflows offered as tools, and their tool definitions."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import FlowDefinition, FlowDefinitionVersion, Session
from ...tools.context import ToolContext
from ..flow_process_summary import render_flow_process_for_tool_description, summarize_flow_process
from ..flow_version_state import FRAGMENT_EXECUTION_KIND
from .naming import workflow_tool_name_for_key


async def list_flow_capabilities(
    db: AsyncSession,
    *,
    project_id: str | None = None,
    include_hidden: bool = False,
) -> list[dict[str, Any]]:
    rows = (
        await db.execute(
            select(FlowDefinitionVersion, FlowDefinition)
            .join(FlowDefinition, FlowDefinition.id == FlowDefinitionVersion.flow_id)
            .where(
                FlowDefinitionVersion.status == "published",
                FlowDefinition.status == "published",
                FlowDefinition.is_active.is_(True),
                FlowDefinition.current_version_id == FlowDefinitionVersion.id,
            )
            .order_by(FlowDefinition.updated_at.desc())
        )
    ).all()

    capabilities: list[dict[str, Any]] = []
    for version, flow in rows:
        capability = _serialize_capability(flow, version, project_id=project_id)
        if include_hidden or capability["available"]:
            capabilities.append(capability)
    return _deduplicate_capabilities(capabilities, project_id=project_id)


async def list_flow_tool_definitions(db: AsyncSession, tool_context: ToolContext) -> list[dict[str, Any]]:
    project_id = await _context_project_id(db, tool_context)
    return [
        _capability_tool_definition(capability)
        for capability in await list_flow_capabilities(db, project_id=project_id, include_hidden=False)
    ]


def _serialize_capability(
    flow: FlowDefinition,
    version: FlowDefinitionVersion,
    *,
    project_id: str | None,
) -> dict[str, Any]:
    definition = dict(version.definition_json or {})
    metadata = _normalized_publish_metadata(flow, version)
    hidden_reason = _hidden_reason(flow, metadata, project_id=project_id)
    input_schema = _flow_input_schema(definition)
    output_schema = _flow_output_schema(definition)
    process_summary = summarize_flow_process(definition)
    evidence_contract = metadata.get("evidence_contract") if isinstance(metadata.get("evidence_contract"), dict) else {}
    cost_budget_hint = metadata.get("cost_budget_hint") if isinstance(metadata.get("cost_budget_hint"), dict) else {}
    return {
        "tool_name": workflow_tool_name_for_key(flow.key, flow.name),
        "flow_id": flow.id,
        "flow_key": flow.key,
        "name": flow.name,
        "description": flow.description or "",
        "version_id": version.id,
        "version": version.version,
        "project_id": flow.project_id,
        "available": hidden_reason is None,
        "hidden_reason": hidden_reason,
        "input_schema": input_schema,
        "output_schema": output_schema,
        "process_summary": process_summary,
        "purpose": str(metadata.get("purpose") or flow.description or flow.name).strip(),
        "evidence_contract": evidence_contract,
        "limitations": [str(item) for item in metadata.get("limitations") or [] if str(item).strip()],
        "examples": [str(item) for item in metadata.get("examples") or [] if str(item).strip()],
        "cost_budget_hint": cost_budget_hint,
        "approval_requirements": metadata.get("approval_requirements")
        if isinstance(metadata.get("approval_requirements"), dict)
        else {},
        "publish_metadata": metadata,
    }


def _normalized_publish_metadata(flow: FlowDefinition, version: FlowDefinitionVersion) -> dict[str, Any]:
    metadata = dict(version.publish_metadata or {})
    definition = dict(version.definition_json or {})
    definition_metadata = definition.get("metadata") if isinstance(definition.get("metadata"), dict) else {}
    evidence_contract = metadata.get("evidence_contract") or definition.get("evidence_contract")
    return {
        **metadata,
        "workflow_key": metadata.get("workflow_key") or flow.key,
        "workflow_name": metadata.get("workflow_name") or flow.name,
        "llm_visible": metadata.get("llm_visible", metadata.get("capability_exposed", True)),
        "capability_enabled": metadata.get("capability_enabled", True),
        "purpose": metadata.get("purpose") or definition_metadata.get("purpose") or flow.description or flow.name,
        "evidence_contract": evidence_contract if isinstance(evidence_contract, dict) else {},
        "execution_kind": definition.get("execution_kind"),
    }


def _hidden_reason(flow: FlowDefinition, metadata: dict[str, Any], *, project_id: str | None) -> str | None:
    if metadata.get("execution_kind") == FRAGMENT_EXECUTION_KIND:
        return "A fragment is part of a workflow, not a tool."
    if metadata.get("capability_enabled") is False:
        return "Workflow capability is disabled."
    if metadata.get("execution_kind") == "phased":
        return "A workflow that runs in phases starts as a workflow run, not as a tool."
    if metadata.get("llm_visible") is False:
        return "Workflow capability is hidden from LLM tool catalogs."
    if flow.project_id and project_id and flow.project_id != project_id:
        return "Workflow belongs to a different project."
    allowed_projects = metadata.get("allowed_projects")
    if project_id and isinstance(allowed_projects, list) and allowed_projects:
        allowed = {str(item or "").strip() for item in allowed_projects if str(item or "").strip()}
        if project_id not in allowed:
            return "Project is not in the workflow capability allowlist."
    if not project_id and flow.project_id:
        return None
    return None


def _capability_tool_definition(capability: dict[str, Any]) -> dict[str, Any]:
    description_parts = [
        capability["purpose"],
        f"Workflow capability `{capability['name']}` version {capability['version']}.",
        # When/when-not framing (model-side catalog contract): a run_flow_*
        # capability is the published governed process — prefer it over
        # improvising the same steps with individual tools; skip it when the
        # request does not match its purpose.
        "WHEN: the user request matches this capability's purpose — run it instead of improvising the "
        "same steps with individual tools. WHEN NOT: requests outside its purpose.",
    ]
    if capability["evidence_contract"]:
        description_parts.append("Returns evidence-traceable workflow output.")
    process_description = render_flow_process_for_tool_description(capability.get("process_summary") or [])
    if process_description:
        description_parts.append(process_description)
    if capability["limitations"]:
        description_parts.append("Limitations: " + "; ".join(capability["limitations"][:3]))
    return {
        "type": "function",
        "function": {
            "name": capability["tool_name"],
            "description": " ".join(part for part in description_parts if part)[:1024],
            "parameters": _as_object_schema(capability["input_schema"]),
        },
    }


def _as_object_schema(schema: Any) -> dict[str, Any]:
    if isinstance(schema, dict) and schema.get("type") == "object":
        return dict(schema)
    if isinstance(schema, dict) and schema.get("properties"):
        return {"type": "object", **schema}
    return {"type": "object", "additionalProperties": True}


def _flow_input_schema(definition: dict[str, Any]) -> dict[str, Any]:
    explicit = definition.get("input_schema")
    if isinstance(explicit, dict):
        return explicit
    for node in definition.get("nodes") or []:
        if not isinstance(node, dict) or str(node.get("type") or "") not in {"input", "input_schema", "trigger"}:
            continue
        for key in ("output_schema", "input_schema"):
            value = node.get(key)
            if isinstance(value, dict) and value:
                return value
        config = node.get("config") if isinstance(node.get("config"), dict) else {}
        if isinstance(config.get("schema"), dict):
            return config["schema"]
    return {"type": "object", "additionalProperties": True}


def _flow_output_schema(definition: dict[str, Any]) -> dict[str, Any]:
    explicit = definition.get("output_schema")
    if isinstance(explicit, dict):
        return explicit
    for node in definition.get("nodes") or []:
        if not isinstance(node, dict) or str(node.get("type") or "") != "output":
            continue
        value = node.get("output_schema") or node.get("input_schema")
        if isinstance(value, dict) and value:
            return value
    return {"type": "object", "additionalProperties": True}


async def _get_capability_for_tool(
    db: AsyncSession,
    *,
    tool_name: str,
    project_id: str | None,
) -> dict[str, Any] | None:
    for capability in await list_flow_capabilities(db, project_id=project_id, include_hidden=False):
        if capability["tool_name"] == tool_name:
            return capability
    return None


def _deduplicate_capabilities(capabilities: list[dict[str, Any]], *, project_id: str | None) -> list[dict[str, Any]]:
    selected: dict[str, dict[str, Any]] = {}
    for capability in capabilities:
        existing = selected.get(capability["tool_name"])
        if existing is None:
            selected[capability["tool_name"]] = capability
            continue
        if project_id and capability.get("project_id") == project_id and existing.get("project_id") != project_id:
            selected[capability["tool_name"]] = capability
    return list(selected.values())


def _primary_project_id(context: ToolContext) -> str | None:
    for project_id in context.project_ids or []:
        normalized = str(project_id or "").strip()
        if normalized:
            return normalized
    return None


async def _context_project_id(db: AsyncSession, context: ToolContext) -> str | None:
    session_id = str(getattr(context, "session_id", "") or "").strip()
    if session_id:
        session = await db.get(Session, session_id)
        if session is not None:
            project_id = str(session.project_id or "").strip()
            if project_id:
                return project_id
    return _primary_project_id(context)
