"""The editor of a workflow that runs in phases."""

from __future__ import annotations

import copy
import re
import uuid
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import FlowDefinition, User
from ...models.runtime.flow_definition import FlowDefinitionVersion
from ...tools.definitions import get_tool_definition_metadata
from ..workflow_checks.library import ADVISORY_ONLY_TYPES, CHECK_TYPES
from ..workflow_checks.steps import STEP_MODES
from .canvas_layout import (
    DIRECTION_KEY,
    GROUPS_KEY,
    POSITIONS_KEY,
    clean_positions,
    layout_direction,
    layout_groups,
    layout_positions,
    with_clean_layout,
    with_layout,
)
from .fragments.store import NODE_READ_ONLY, composition_of, fragment_origin_nodes, pinned_source
from .graph import EXECUTION_KIND_KEY, EXECUTION_KIND_PHASED, NODE_PHASE, is_phased_definition, parse_phased_definition
from .graph_validation import validate_phased_definition
from .phase_steps_graph import GraphShapeError, definition_from_graph, definition_graph


def _http(status: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status, detail={"code": code, "message": message})


async def _flow_and_version(db: AsyncSession, flow_id: str) -> tuple[FlowDefinition, FlowDefinitionVersion]:
    flow = await db.get(FlowDefinition, flow_id)
    if flow is None:
        raise _http(404, "unknown_flow", "The workflow does not exist.")
    latest = (await db.execute(
        select(FlowDefinitionVersion).where(FlowDefinitionVersion.flow_id == flow_id)
        .order_by(FlowDefinitionVersion.version.desc()).limit(1)
    )).scalar_one_or_none()
    if latest is None or not is_phased_definition(dict(latest.definition_json or {})):
        raise _http(409, "not_phased", "This workflow does not run in phases.")
    return flow, latest


def _node_summary(node: Any) -> dict[str, Any]:
    contract = node.config.get("workflow_contract") if isinstance(node.config.get("workflow_contract"), dict) else {}
    summary: dict[str, Any] = {"id": node.id, "kind": node.kind, "title": node.title}
    if node.kind == NODE_PHASE:
        summary.update(capability_class=contract.get("capability_class"),
                       steps=len(contract.get("source_steps") or []), checks=len(contract.get("checks") or []),
                       path_rules=list(dict(contract.get("path_rules") or {}).get("write") or []))
    for key in ("agent", "outcome", "subject", "question", "tool", "workflow_key", "conditions", "source", "options",
                "action", "output", "inputs", "shows", "handoff"):
        if key in node.config:
            summary[key] = copy.deepcopy(node.config[key])
    if node.kind == "gate":
        summary["checks"] = len(node.config.get("checks") or [])
    summary["config"] = copy.deepcopy(node.config)
    return summary


def _layout_view(definition: dict[str, Any], nodes: frozenset[str]) -> dict[str, Any]:
    layout: dict[str, Any] = {POSITIONS_KEY: layout_positions(definition, nodes)}
    groups = layout_groups(definition, nodes)
    if groups is not None:
        layout[GROUPS_KEY] = groups
    if layout_direction(definition):
        layout[DIRECTION_KEY] = layout_direction(definition)
    return layout


async def phased_view(db: AsyncSession, flow_id: str, *, user_id: str | None = None) -> dict[str, Any]:
    from ..flow_publish_review import publish_permission

    flow, version = await _flow_and_version(db, flow_id)
    permission = await publish_permission(db, version, user_id) if user_id else {"can_publish": True,
                                                                                  "publish_reason": ""}
    definition = dict(version.definition_json or {})
    graph = parse_phased_definition(definition)
    published = await db.get(FlowDefinitionVersion, flow.current_version_id or "")
    composite = composition_of(version) is not None
    return {
        "flow_id": flow.id, "key": flow.key, "title": flow.name, "description": flow.description or "",
        "project_id": flow.project_id,
        "status": flow.status, "version_id": version.id, "version": version.version,
        "version_status": version.status,
        "published_version": published.version if published is not None and published.status == "published" else None,
        "editable": flow.status != "archived" and bool(flow.is_active),
        "nodes": [_node_summary(node) for node in graph.ordered_nodes()],
        "edges": [{"id": edge.id, "source": edge.source, "target": edge.target, "kind": edge.kind, "when": edge.when,
                   "max_iterations": edge.max_iterations, "title": edge.title} for edge in graph.edges],
        "validation_report": validate_phased_definition(definition),
        "layout": _layout_view(definition, frozenset(graph.nodes)),
        "definition": copy.deepcopy(definition),
        # Built from fragments: its structure is changed in the fragments, the designer moves boxes only.
        "composite": composite,
        "review_state": str(dict(dict(version.publish_metadata or {}).get("review") or {}).get("state") or "") or None,
        # Four eyes for this viewer (computed on the server): the author sees Publish disabled with the reason.
        **permission,
    }


def _phase_payload(definition: dict[str, Any], node_id: str) -> dict[str, Any]:
    node = parse_phased_definition(definition).nodes.get(node_id)
    if node is None or node.kind != NODE_PHASE:
        raise _http(404, "unknown_phase", "The phase does not exist in this workflow version.")
    config = node.config
    contract = dict(config.get("workflow_contract") or {})
    return {
        "workflow_id": config.get("workflow_id") or contract.get("workflow_id"),
        "workflow_class": config.get("workflow_class") or contract.get("workflow_class"),
        "workflow_contract": contract, "tool_policy": dict(config.get("tool_policy") or {}),
        "safety_constraints": dict(config.get("safety_constraints") or {}),
    }


def _requires_approval(name: str) -> bool:
    return get_tool_definition_metadata(name).approval_required


async def phase_graph_view(db: AsyncSession, flow_id: str, node_id: str) -> dict[str, Any]:
    flow, version = await _flow_and_version(db, flow_id)
    definition = dict(version.definition_json or {})
    payload = _phase_payload(definition, node_id)
    node = parse_phased_definition(definition).nodes[node_id]
    from .phase_validation import validate_phase_payload

    return {
        "policy_id": flow.id, "key": f"{flow.key}#{node_id}", "title": f"{flow.name} · {node.title}",
        "status": flow.status, "project_id": flow.project_id, "version_id": version.id, "version": version.version,
        "version_status": version.status, "published_version": None, "pending_draft": False,
        "validation_report": validate_phase_payload(payload),
        "editable": flow.status != "archived" and bool(flow.is_active), "read_only_reason": None,
        "check_types": list(CHECK_TYPES), "advisory_check_types": sorted(ADVISORY_ONLY_TYPES),
        "step_modes": list(STEP_MODES),
        "graph": definition_graph(payload, tool_requires_approval=_requires_approval),
        "phase": {"flow_id": flow.id, "node_id": node_id, "title": node.title},
    }


def _with_contract(definition: dict[str, Any], node_id: str, contract: dict[str, Any]) -> dict[str, Any]:
    edited = copy.deepcopy(definition)
    for raw in edited.get("nodes") or []:
        if isinstance(raw, dict) and str(raw.get("id") or "") == node_id:
            raw["config"] = {**dict(raw.get("config") or {}), "workflow_contract": copy.deepcopy(contract)}
    return edited


def _edited_phase(definition: dict[str, Any], node_id: str, graph: Any) -> tuple[dict[str, Any], dict[str, Any]]:
    try:
        payload = definition_from_graph(_phase_payload(definition, node_id), graph or {})
    except GraphShapeError as error:
        raise _http(422, error.code, str(error)) from error
    return payload, _with_contract(definition, node_id, payload["workflow_contract"])


async def preview_phase_graph(db: AsyncSession, flow_id: str, node_id: str, body: dict[str, Any]) -> dict[str, Any]:
    from .phase_validation import validate_phase_payload

    _flow, version = await _flow_and_version(db, flow_id)
    payload, _edited = _edited_phase(dict(version.definition_json or {}), node_id, body.get("graph"))
    return {"graph": definition_graph(payload, tool_requires_approval=_requires_approval),
            "validation_report": validate_phase_payload(payload)}


async def _save(db: AsyncSession, flow: FlowDefinition, base: FlowDefinitionVersion, definition: dict[str, Any],
                user: User) -> None:
    from ..flow_draft_service import save_flow_draft

    await save_flow_draft(db, flow_id=flow.id, current_user=user, payload={
        "expected_latest_version_id": base.id, "definition": definition, "name": flow.name,
        "description": flow.description or "",
    })


def _require_base(version: FlowDefinitionVersion, body: dict[str, Any]) -> None:
    if str(body.get("base_version_id") or "") != version.id:
        raise _http(409, "stale_base_version", "The workflow changed since it was opened; reload it.")


async def save_phase_graph(
    db: AsyncSession, flow_id: str, node_id: str, *, user: User, body: dict[str, Any]
) -> dict[str, Any]:
    flow, version = await _flow_and_version(db, flow_id)
    _require_base(version, body)
    if node_id in fragment_origin_nodes(version):
        raise _http(409, NODE_READ_ONLY, "This step comes from a fragment: change the fragment and re-pin it.")
    payload, edited = _edited_phase(dict(version.definition_json or {}), node_id, body.get("graph"))
    block = composition_of(version)
    if block is not None:
        # A composite is saved as its source (same pins), so the new draft is compiled again with provenance.
        edited = _with_contract(pinned_source(block), node_id, payload["workflow_contract"])
    await _save(db, flow, version, edited, user)
    return await phase_graph_view(db, flow_id, node_id)


async def save_phased_layout(db: AsyncSession, flow_id: str, *, user: User, body: dict[str, Any]) -> dict[str, Any]:
    # Never publishes: a published workflow keeps running its version until someone publishes the draft.
    flow, version = await _flow_and_version(db, flow_id)
    _require_base(version, body)
    definition = dict(version.definition_json or {})
    nodes = frozenset(parse_phased_definition(definition).nodes)
    positions = clean_positions(body.get("positions"), nodes)
    if positions == layout_positions(definition, nodes):
        return await phased_view(db, flow_id, user_id=user.id)
    block = composition_of(version)
    # A composite is saved as its source (same pins); the compiler copies the layout block through unchanged.
    source = pinned_source(block) if block is not None else definition
    await _save(db, flow, version, with_layout(source, positions), user)
    return await phased_view(db, flow_id, user_id=user.id)


def starter_definition() -> dict[str, Any]:
    return {
        EXECUTION_KIND_KEY: EXECUTION_KIND_PHASED,
        "nodes": [
            {"id": "start", "type": "start", "label": "Start", "config": {}},
            {"id": "end", "type": "outcome", "label": "Done", "config": {"outcome": "done"}},
        ],
        "edges": [{"id": "e-start", "source_node_id": "start", "target_node_id": "end"}],
    }


def _new_key(title: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:60] or "workflow"
    return f"{slug}-{uuid.uuid4().hex[:6]}"


async def create_phased_workflow(db: AsyncSession, *, user: User, body: dict[str, Any]) -> dict[str, Any]:
    from ..flow_definitions import create_flow_definition

    title = str(body.get("title") or "").strip()[:220] or "New workflow"
    created = await create_flow_definition(db, current_user=user, payload={
        "key": _new_key(title), "name": title, "description": str(body.get("description") or "").strip(),
        "definition": starter_definition(),
    })
    return await phased_view(db, created["id"], user_id=user.id)


async def save_phased_definition(
    db: AsyncSession, flow_id: str, *, user: User, body: dict[str, Any]
) -> dict[str, Any]:
    flow, version = await _flow_and_version(db, flow_id)
    _require_base(version, body)
    if composition_of(version) is not None and body.get("detach") is not True:
        raise _http(409, "composite_structure", "This workflow is built from fragments: change its boxes in the "
                                                "fragments, or make an editable copy with \"Edit as draft\".")
    # detach: a person edits a workflow built from fragments by hand. The draft stores the compiled boxes as a plain
    # definition, so it no longer follows its fragments; the published version keeps running until it is published.
    definition = body.get("definition")
    if not isinstance(definition, dict):
        raise _http(422, "definition_required", "The workflow to save is missing.")
    definition = {**copy.deepcopy(definition), EXECUTION_KIND_KEY: EXECUTION_KIND_PHASED}
    definition = with_clean_layout(definition, frozenset(parse_phased_definition(definition).nodes))
    title = body.get("title")
    if title is not None and (not isinstance(title, str) or not title.strip() or len(title.strip()) > 220):
        raise _http(422, "title_invalid", "Give the workflow a name of 1 to 220 characters.")
    from ..flow_draft_service import save_flow_draft

    await save_flow_draft(db, flow_id=flow.id, current_user=user, payload={
        "expected_latest_version_id": version.id, "definition": definition,
        "name": title.strip() if isinstance(title, str) else flow.name, "description": flow.description or "",
    })
    return await phased_view(db, flow_id, user_id=user.id)


__all__ = [
    "create_phased_workflow",
    "phase_graph_view",
    "phased_view",
    "preview_phase_graph",
    "save_phase_graph",
    "save_phased_definition",
    "save_phased_layout",
    "starter_definition",
]
