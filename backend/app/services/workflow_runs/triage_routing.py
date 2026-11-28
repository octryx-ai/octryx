"""Routing by type after the triage ("Routing by type")."""

from __future__ import annotations

import logging
import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import AuditLog, Project, User, WorkflowRun
from ...models.runtime.secure_work import WorkItem
from ...time_utils import utc_now
from .definition_of_ready import DOR_KEY, TRIAGE_WORKFLOW_KEY
from .records import WorkflowRunError, record_event
from .states import OUTCOME_DELIVERED, OUTCOME_DONE

logger = logging.getLogger(__name__)

CONFIG_KEY = "triage_routing"
ROUTING_KEY = "routing"
ROUTED_FROM_KEY = "routed_from"
AUDIT_ACTION = "workflow_run.triage_routing_updated"
INCIDENT_WORKFLOW_KEY = "incident-analysis"
DEFAULT_ROUTES: dict[str, str] = {
    "feature": "epic-delivery",
    "bug": "bug-fix-reproduction",
    "incident": INCIDENT_WORKFLOW_KEY,
}
EVENT_ROUTED_TO = "routed_to"
EVENT_ROUTED_FROM = "routed_from"
EVENT_NO_ROUTE = "routing_no_route"
EVENT_ROUTING_FAILED = "routing_failed"
STATE_ROUTED, STATE_NO_ROUTE, STATE_FAILED = "routed", "no_route", "failed"
SUCCESS_OUTCOMES = frozenset({OUTCOME_DONE, OUTCOME_DELIVERED})
JIRA_INCIDENT_TYPE = "incident"  # Jira issue type "Incident" (case-insensitive)
SERVICENOW_INCIDENT_TABLE = "incident"  # ServiceNow items keep their table as ``issue_type``
MAX_ROUTES = 30
_TYPE = re.compile(r"^[a-z][a-z0-9_-]{0,39}$")
_KEY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,179}$")


class RoutingSettingsError(ValueError):
    def __init__(self, code: str, field: str) -> None:
        super().__init__(f"{field}: {code}")
        self.code = code
        self.field = field


def normalize_routes(value: Any, field: str = f"{CONFIG_KEY}.routes") -> dict[str, str | None]:
    if not isinstance(value, dict):
        raise RoutingSettingsError("object_required", field)
    if len(value) > MAX_ROUTES:
        raise RoutingSettingsError("too_many_routes", field)
    routes: dict[str, str | None] = {}
    for raw_type, raw_key in value.items():
        kind = str(raw_type or "").strip().lower()
        if not _TYPE.match(kind):
            raise RoutingSettingsError("type_invalid", f"{field}.{raw_type}")
        if raw_key is None or (isinstance(raw_key, str) and not raw_key.strip()):
            routes[kind] = None
            continue
        if not isinstance(raw_key, str) or not _KEY.match(raw_key.strip()):
            raise RoutingSettingsError("workflow_key_invalid", f"{field}.{kind}")
        if raw_key.strip() == TRIAGE_WORKFLOW_KEY:
            raise RoutingSettingsError("route_to_triage", f"{field}.{kind}")
        routes[kind] = raw_key.strip()
    return routes


def normalize_settings(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise RoutingSettingsError("object_required", CONFIG_KEY)
    unknown = sorted(str(key) for key in set(value) - {"routes"})
    if unknown:
        raise RoutingSettingsError("unknown_key", f"{CONFIG_KEY}.{unknown[0]}")
    return {"routes": normalize_routes(value.get("routes", {}))}


def normalize_config_value(value: Any) -> Any:
    return None if value is None else normalize_settings(value)


def workspace_routes(config: Any) -> tuple[dict[str, str | None], str]:
    stored = config.get(CONFIG_KEY) if isinstance(config, dict) else None
    if stored is None:
        return {}, "default"
    try:
        return normalize_settings(stored)["routes"], "workspace"
    except RoutingSettingsError:
        return {}, "invalid"


def definition_routes(node: Any) -> dict[str, str | None] | None:
    config = getattr(node, "config", None) or {}
    block = config.get(ROUTING_KEY) if isinstance(config, dict) else None
    if not isinstance(block, dict):
        return None
    try:
        return normalize_routes(block.get("routes", {}), f"{getattr(node, 'id', 'node')}.routing.routes")
    except RoutingSettingsError:
        return None


def routing_errors(node: Any) -> list[dict[str, str]]:
    config = getattr(node, "config", None) or {}
    if ROUTING_KEY not in config:
        return []
    block = config[ROUTING_KEY]
    message = (f"Outcome '{node.id}' routing is {{\"routes\": {{type: workflow key or null}}}}: lower-case types, "
               "workflow keys, never the triage itself.")
    if not isinstance(block, dict) or set(block) - {"routes"}:
        return [{"code": "outcome_routing", "message": message}]
    try:
        normalize_routes(block.get("routes", {}))
    except RoutingSettingsError:
        return [{"code": "outcome_routing", "message": message}]
    return []


def effective_routes(workspace: dict[str, str | None] | None = None,
                     definition: dict[str, str | None] | None = None) -> dict[str, str | None]:
    return {**DEFAULT_ROUTES, **dict(workspace or {}), **dict(definition or {})}


async def routes_for_workspace(db: AsyncSession, project_id: str | None) -> dict[str, str | None]:
    project = await db.get(Project, project_id) if project_id else None
    return effective_routes(workspace_routes(project.config if project is not None else None)[0])


def is_incident(item: WorkItem | None) -> bool:
    if item is None:
        return False
    source = str(item.source_type or "").strip().lower()
    kind = str(item.issue_type or "").strip().lower()
    return (source == "jira" and kind == JIRA_INCIDENT_TYPE) or (
        source == "servicenow" and kind == SERVICENOW_INCIDENT_TABLE)


def entry_workflow_for(work_item: WorkItem | None, routes: dict[str, str | None] | None = None) -> str:
    if not is_incident(work_item):
        return TRIAGE_WORKFLOW_KEY
    mapped = (DEFAULT_ROUTES if routes is None else routes).get("incident", INCIDENT_WORKFLOW_KEY)
    return mapped or TRIAGE_WORKFLOW_KEY


def routing_state(run: WorkflowRun) -> dict[str, Any]:
    return dict(dict(run.context or {}).get(ROUTING_KEY) or {})


def routing_view(run: WorkflowRun) -> dict[str, Any] | None:
    state = routing_state(run)
    origin = dict(dict(run.context or {}).get(ROUTED_FROM_KEY) or {})
    if not state and not origin:
        return None
    view = {key: state.get(key) for key in ("state", "type", "workflow_key", "run_id", "message", "code", "at")
            if state.get(key) is not None}
    if origin:
        view[ROUTED_FROM_KEY] = {key: origin.get(key) for key in ("run_id", "workflow_key", "type")}
    return view


def _definition_of_ready(run: WorkflowRun) -> dict[str, Any]:
    from .phase_outputs import recorded_output

    envelope = recorded_output(run, DOR_KEY) or {}
    record = envelope.get("record") if isinstance(envelope.get("record"), dict) else None
    if record is None:
        record = {key: value for key, value in dict(dict(run.context or {}).get(DOR_KEY) or {}).items() if key != "at"}
    return dict(record)


async def _ending_node(db: AsyncSession, run: WorkflowRun):
    from .graph import graph_for_run

    return (await graph_for_run(db, run)).nodes.get(run.current_node_id or "")


async def routes_for_run(db: AsyncSession, run: WorkflowRun, node: Any = None) -> dict[str, str | None]:
    project = await db.get(Project, run.project_id) if run.project_id else None
    workspace = workspace_routes(project.config if project is not None else None)[0]
    return effective_routes(workspace, definition_routes(node if node is not None else await _ending_node(db, run)))


async def _existing_follow_up(db: AsyncSession, run: WorkflowRun) -> WorkflowRun | None:
    return (await db.execute(select(WorkflowRun).where(
        WorkflowRun.work_item_id == run.work_item_id, WorkflowRun.id != run.id,
        WorkflowRun.context[ROUTED_FROM_KEY]["run_id"].as_string() == run.id,
    ).limit(1))).scalars().first() if run.work_item_id else None


async def _follow_up_target(db: AsyncSession, run: WorkflowRun, requester: User) -> tuple[Any, str | None]:
    from .runtime_target.target import KIND_SERVER, stored_target, validate_target

    stored = stored_target(run)
    if stored is None:
        return None, None
    raw = {key: stored[key] for key in ("kind", "device_id", "folder", "profile", "model") if stored.get(key)}
    try:
        await validate_target(db, user=requester, project_id=run.project_id, raw=raw, repository=run.repository)
    except WorkflowRunError as error:
        return {"kind": KIND_SERVER}, error.code
    return raw, None


def _set_state(run: WorkflowRun, value: dict[str, Any]) -> None:
    run.context = {**dict(run.context or {}), ROUTING_KEY: {**value, "at": utc_now().isoformat()}}


def is_routed_triage(run: WorkflowRun, node: Any) -> bool:
    return run.workflow_key == TRIAGE_WORKFLOW_KEY or definition_routes(node) is not None


async def route_after_triage(db: AsyncSession, run: WorkflowRun, *, actor_id: str | None) -> WorkflowRun | None:
    if run.parent_run_id or run.outcome not in SUCCESS_OUTCOMES or routing_state(run):
        return None
    node = await _ending_node(db, run)
    if not is_routed_triage(run, node):
        return None
    if (existing := await _existing_follow_up(db, run)) is not None:
        _set_state(run, {"state": STATE_ROUTED, "workflow_key": existing.workflow_key, "run_id": existing.id,
                         "type": dict(dict(existing.context or {}).get(ROUTED_FROM_KEY) or {}).get("type")})
        return None
    record = _definition_of_ready(run)
    kind = str(record.get("type") or "").strip().lower()
    routes = await routes_for_run(db, run, node)
    key = routes.get(kind) if kind else None
    if not key:
        message = f"No route for type '{kind}'" if kind else "No route: the triage recorded no type"
        _set_state(run, {"state": STATE_NO_ROUTE, "type": kind or None, "message": message})
        record_event(db, run, EVENT_NO_ROUTE, node_id=run.current_node_id, actor_id=actor_id,
                     detail={"type": kind or None, "message": message,
                             **({"switched_off": True} if kind in routes else {})})
        return None
    return await _start_follow_up(db, run, key=key, kind=kind, record=record, actor_id=actor_id)


async def _start_follow_up(db: AsyncSession, run: WorkflowRun, *, key: str, kind: str, record: dict[str, Any],
                           actor_id: str | None) -> WorkflowRun | None:
    from .phase_outputs import HANDOFF_KEY
    from .records import new_chat_session, start_run

    def failed(code: str, message: str) -> None:
        _set_state(run, {"state": STATE_FAILED, "type": kind, "workflow_key": key, "code": code, "message": message})
        record_event(db, run, EVENT_ROUTING_FAILED, node_id=run.current_node_id, actor_id=actor_id,
                     detail={"type": kind, "workflow_key": key, "code": code, "message": message[:500]})

    requester = await db.get(User, run.requested_by) if run.requested_by else None
    if requester is None or not requester.is_active:
        failed("requester_inactive", "The triage's requester is no longer active; start the follow-up by hand.")
        return None
    target, fallback = await _follow_up_target(db, run, requester)
    origin = {"run_id": run.id, "workflow_key": run.workflow_key, "type": kind, "at": utc_now().isoformat()}
    inherited = {name: value for name, value in dict(run.context or {}).items() if name == "jira_project_key"}
    context = {**inherited, HANDOFF_KEY: {DOR_KEY: record}, ROUTED_FROM_KEY: origin}
    try:
        async with db.begin_nested():  # a refused start leaves neither a thread nor a half-started run behind
            thread = await new_chat_session(db, requester, run.project_id)
            child = await start_run(
                db, user=requester, workflow_key=key, project_id=run.project_id, work_item_id=run.work_item_id,
                repository=run.repository, session=thread, ticket_key=run.ticket_key, context=context,
                runtime_target=target, responsible=(run.responsible_user_id, run.responsible_source),
            )
    except WorkflowRunError as error:
        failed(error.code, str(error))
        return None
    except Exception as error:  # noqa: BLE001 - the triage's own completion stands; the failure is on record
        logger.exception("Follow-up of triage run %s could not start", run.id)
        failed("start_error", type(error).__name__)
        return None
    record_event(db, child, EVENT_ROUTED_FROM, node_id=child.current_node_id, actor_id=actor_id,
                 detail={"workflow_key": run.workflow_key, "run_id": run.id, "type": kind})
    _set_state(run, {"state": STATE_ROUTED, "type": kind, "workflow_key": key, "run_id": child.id})
    record_event(db, run, EVENT_ROUTED_TO, node_id=run.current_node_id, actor_id=actor_id, detail={
        "workflow_key": key, "run_id": child.id, "type": kind,
        "runtime_target": (target or {}).get("kind") if isinstance(target, dict) else None,
        **({"runtime_target_fallback": fallback} if fallback else {}),
    })
    return child


def settings_payload(project: Project, *, can_edit: bool) -> dict[str, Any]:
    routes, source = workspace_routes(project.config)
    return {"project_id": project.id, "routes": routes, "defaults": dict(DEFAULT_ROUTES),
            "effective": effective_routes(routes), "source": source, "can_edit": can_edit}


async def set_workspace_routes(db: AsyncSession, *, project: Project, value: Any, actor_id: str) -> dict[str, Any]:
    from ..admin.project.admin_project_config_service import apply_project_config_patch

    section = normalize_settings(value)
    before = (project.config or {}).get(CONFIG_KEY) if isinstance(project.config, dict) else None
    await apply_project_config_patch(db, project=project, patch={CONFIG_KEY: section}, actor_user_id=actor_id,
                                     replace_keys=frozenset({CONFIG_KEY}))
    db.add(AuditLog(user_id=actor_id, action=AUDIT_ACTION, resource_type="workspace", resource_id=project.id,
                    details={"before": before, "after": section}))
    await db.flush()
    return section


__all__ = [
    "CONFIG_KEY",
    "DEFAULT_ROUTES",
    "EVENT_NO_ROUTE",
    "EVENT_ROUTED_FROM",
    "EVENT_ROUTED_TO",
    "EVENT_ROUTING_FAILED",
    "INCIDENT_WORKFLOW_KEY",
    "ROUTED_FROM_KEY",
    "ROUTING_KEY",
    "RoutingSettingsError",
    "definition_routes",
    "effective_routes",
    "entry_workflow_for",
    "is_incident",
    "normalize_config_value",
    "normalize_routes",
    "normalize_settings",
    "route_after_triage",
    "routes_for_run",
    "routes_for_workspace",
    "routing_errors",
    "routing_view",
    "set_workspace_routes",
    "settings_payload",
    "workspace_routes",
]
