"""Routes, callers and answer comparison for the foreign-private walker (``test_foreign_private_walker``)."""

from __future__ import annotations

import asyncio
import re
import uuid
from dataclasses import dataclass
from urllib.parse import urlencode

from fastapi.routing import APIRoute
from sqlalchemy import select

from app.main import app
from app.services.project.private_workspace import ensure_private_workspace
from tests.data_access.foreign_private_rows import ForeignPrivateRows, Seeded, seed_foreign_private_rows
from tests.devices.device_support import user_named
from tests.knowledge_evidence_seed_support import seed_member, seed_workspace
from tests.policy_engine_support import bearer
from tests.workspace_id_route_support import _TIMESTAMP, answer_text, refusal_code, stable_headers

WORKSPACE_PARAMS = frozenset({"workspace_id", "project_id"})
# The tables a path parameter can name; the walker tries the seeded row of each.
ID_PARAMS: dict[str, tuple[str, ...]] = {
    "session_id": ("sessions",),
    "work_item_id": ("work_items",),
    "run_id": ("workflow_runs", "agent_chain_runs", "product_runs"),
    "worker_id": ("agent_workers",),
    "job_id": ("device_jobs", "data_import_jobs", "data_export_jobs"),
    "flow_id": ("flow_definitions",),
    "task_id": ("tasks",),
    "source_id": ("knowledge_evidence_sources", "knowledge_source_connectors"),
    "install_id": ("plugin_installs",),
    "connection_id": ("connector_named_connections", "rest_api_connections", "database_connectors"),
    "revision_id": ("knowledge_source_revisions", "agent_definition_revisions"),
    "repository_id": ("code_repositories",),
    "profile_id": ("work_repository_profiles",),
    "policy_id": ("model_policies", "budget_policies"),
    "package_id": ("knowledge_packages", "export_packages"),
    "node_id": ("knowledge_graph_nodes", "engineering_knowledge_graph_nodes", "knowledge_structured_nodes"),
    "definition_id": ("agent_definitions", "work_item_workflow_definitions", "rest_api_connections"),
    "webhook_id": ("webhooks", "outbound_webhooks"),
    "message_id": ("agent_board_message",),
    "intake_id": ("work_item_sync_configs",),
    "handoff_id": ("work_item_handoff", "workflow_handoffs"),
    "decision_id": ("connector_watcher_rule_decisions", "policy_decision_log"),
    "channel_id": ("channel_configs",),
    "attachment_id": ("work_item_handoff_attachment",),
    "agent_id": ("agent_definitions", "agent_workers"),
    "takeover_id": ("work_item_takeover",),
    "server_id": ("mcp_server_registrations",),
    "role_id": ("work_roles",),
    "question_id": ("clarification_questions",),
    "proposal_id": ("check_proposals", "knowledge_merge_proposals"),
    "approval_id": ("approvals",),
    "config_id": ("call_agent_configs", "work_coding_pipeline_configs"),
    "trace_id": ("turn_traces", "sessions"),
    "file_id": ("knowledge_code_files",),
    "watcher_id": ("connector_watchers",),
    "rule_id": ("connector_watcher_rules",),
    "event_id": ("connector_watcher_events",),
    "group_id": ("agent_groups",),
    "template_id": ("agent_chain_templates", "notification_templates", "design_trace_sync_templates"),
    "artifact_id": ("design_artifacts",),
    "subscription_id": ("notification_subscriptions",),
    "chain_id": ("agent_chain_templates",),
    "build_id": ("knowledge_structured_builds",),
    "build_run_id": ("knowledge_structured_builds",),
    "binding_id": ("knowledge_workspace_bindings", "workspace_capability_bindings"),
    "hold_id": ("knowledge_object_retention_holds",),
    "assignment_id": ("work_role_assignments", "engineering_knowledge_pack_assignments"),
    "function_id": ("work_role_functions",),
    "claim_id": ("work_item_claim",),
    "document_id": ("work_item_documents", "knowledge_package_documents"),
    "analysis_id": ("work_item_analysis",),
    "memory_id": ("knowledge_memory_items",),
    "item_id": ("knowledge_memory_items", "work_items"),
    "entry_id": ("task_queue_entries",),
    "alert_id": ("budget_alerts",),
    "rule_set_id": ("task_routing_rules",),
    "secret_id": ("stored_secrets",),
    "invitation_id": ("user_invitations",),
    "feedback_id": ("knowledge_answer_feedback",),
    "process_id": ("runtime_processes",),
    "conversation_id": ("proactive_conversations",),
    "label_id": ("content_trust_labels",),
    "quarantine_id": ("quarantine_entries",),
    "record_id": ("compliance_audit_records",),
    "evidence_package_id": ("evidence_packages",),
    "tool_id": ("database_query_tools",),
    "delegation_id": ("worker_delegations",),
    "flag_id": (),
}
# Path parameters that never name a row of a Workspace-bound model.
NOT_WORKSPACE_ROWS = frozenset({
    "provider_id", "user_id", "version", "version_id", "skill_id", "key", "name", "connector_key", "connector_name",
    "tool_name", "token", "sha256", "path", "resource_path", "pairing_id", "ident", "call_id", "report_export_id",
    "instruction_id", "entity_type", "entity_id", "node_run_id", "change_plan_id", "revision", "model_id",
    "pack_id", "entity_ref", "commit", "project_key", "slug", "evidence_key", "screen", "kind", "filename",
    "change_unit_id", "device_id", "client_id", "family", "format", "scope", "section", "slot", "state",
})
TIMEOUT_SECONDS = 10
# Server-sent event streams: they answer with a stream that stays open.
STREAM_SUFFIXES = ("/stream", "/events/stream")
_EXPIRES = re.compile(r"expires=[^;]+")
# GET routes that store something on every call, whoever asks: the health checks they run, a Workspace's default
# worker rate limits.
WRITES_ON_READ = frozenset({"/api/v1/health", "/api/v1/observability/health", "/api/v1/observability/overview",
                            "/api/v1/workers/projects/{project_id}/rate-limits"})


@dataclass
class World:
    owner: str
    admin: str
    member: str
    shared: str
    private: str

    def outsiders(self) -> dict[str, str | None]:
        return {"admin": self.admin, "anonymous": None, "member": self.member}


async def world(db) -> World:
    from app.models import Role, UserRole
    from tests.phased_workflow_fixtures import admin_user

    # A platform admin too: admin routes then have a caller that may see the private rows, their owner.
    owner = await user_named(db, f"pg5-owner-{uuid.uuid4().hex[:6]}")
    admin_role = (await db.execute(select(Role).where(Role.name == "admin"))).scalar_one()
    db.add(UserRole(user_id=owner.id, role_id=admin_role.id))
    private = await ensure_private_workspace(db, owner)
    admin = await admin_user(db)
    await ensure_private_workspace(db, admin)
    shared = await seed_workspace(db)
    other = await seed_workspace(db)
    member = await seed_member(db, workspace_id=other, role="member")
    from app.models import User

    await ensure_private_workspace(db, await db.get(User, member))
    await db.commit()
    return World(owner=owner.id, admin=admin.id, member=member, shared=shared, private=private.id)


async def seed(db, scene: World) -> Seeded:
    return await seed_foreign_private_rows(db, scene.private, scene.owner)


async def platform_parents(db, scene: World) -> ForeignPrivateRows:
    rows = ForeignPrivateRows(db, scene.private, scene.owner)
    await rows.platform_parents()
    return rows


def _get_routes() -> list[APIRoute]:
    return sorted((route for route in app.routes if isinstance(route, APIRoute) and "GET" in route.methods),
                  key=lambda route: route.path)


def _required_query(route: APIRoute) -> list[str]:
    return [param.alias or param.name for param in route.dependant.query_params if param.field_info.is_required()]


def list_routes() -> list[APIRoute]:
    return [route for route in _get_routes()
            if not set(_path_params(route)) - WORKSPACE_PARAMS
            and not set(_required_query(route)) - WORKSPACE_PARAMS - ID_PARAMS.keys()]


def _path_params(route: APIRoute) -> list[str]:
    return [param.name for param in route.dependant.path_params]


@dataclass(frozen=True)
class Case:
    route: APIRoute
    param: str
    # Every other ID the request names, from the same seeded family: {parameter: table}
    others: tuple[tuple[str, str], ...]

    @property
    def name(self) -> str:
        return f"{self.route.path} {self.param}"

    @property
    def tables(self) -> tuple[str, ...]:
        # The tables the parameter can name; the owner's answer tells which one the route reads.
        return ID_PARAMS[self.param]


def id_cases() -> list[Case]:
    cases = []
    for route in _get_routes():
        if set(_required_query(route)) - WORKSPACE_PARAMS - ID_PARAMS.keys():
            continue
        named = [param for param in _path_params(route) + _required_query(route) if ID_PARAMS.get(param)]
        cases.extend(Case(route, param, tuple((other, ID_PARAMS[other][0]) for other in named if other != param))
                     for param in named)
    return cases


def unclassified_params() -> set[str]:
    return {param for route in _get_routes() for param in _path_params(route)
            if param not in WORKSPACE_PARAMS | ID_PARAMS.keys() | NOT_WORKSPACE_ROWS}


def row_id(rows: Seeded, table: str) -> str:
    row = rows.rows[table]
    return str(row.get("id") or next(iter(row.values())))


def url(route: APIRoute, workspace_id: str, values: dict[str, str] | None = None) -> str:
    values = values or {}
    path = route.path
    types = {param.name: param.field_info.annotation for param in route.dependant.path_params}
    for name in _path_params(route):
        value = values.get(name) or (workspace_id if name in WORKSPACE_PARAMS else
                                     "1" if types.get(name) is int else str(uuid.uuid4()))
        path = path.replace(f"{{{name}:path}}", value).replace(f"{{{name}}}", value)
    query = {name: values.get(name) or workspace_id for name in _required_query(route)}
    return path + ("?" + urlencode(query) if query else "")


def case_urls(case: Case, table: str, rows: Seeded) -> tuple[str, str, str, str]:
    values = {other: row_id(rows, other_table) for other, other_table in case.others}
    known_id = row_id(rows, table)
    unknown_id = unknown_like(known_id)
    return (url(case.route, rows.workspace_id, {**values, case.param: known_id}),
            url(case.route, rows.workspace_id, {**values, case.param: unknown_id}), known_id, unknown_id)


def unknown_like(value: str) -> str:
    return str(uuid.uuid4()) if len(value) == 36 else str(int(value) + 7) if value.isdigit() else "unknown-id"


class UnexpectedAnswerError(AssertionError):
    pass


async def answer(client, path: str, caller: str | None, *masked: str) -> tuple | None:
    # None: a stream that never ends (STREAMS only). A raised error or another timeout fails the walk.
    try:
        response = await asyncio.wait_for(client.get(path, headers=bearer(caller) if caller else {}),
                                          TIMEOUT_SECONDS)
    except TimeoutError:
        if path.split("?")[0].endswith(STREAM_SUFFIXES):
            return None
        raise UnexpectedAnswerError(f"{path} as {caller}: no answer in {TIMEOUT_SECONDS}s") from None
    except Exception as error:
        raise UnexpectedAnswerError(f"{path} as {caller}: {type(error).__name__}: {error}") from error
    if response.status_code >= 500 and response.status_code != 503:
        raise UnexpectedAnswerError(f"{path} as {caller}: {response.status_code} {response.text[:200]}")
    long_ids = tuple(item for item in masked if len(item) >= 8)
    text = answer_text(response, *long_ids)
    for item in masked:
        if len(item) < 8:  # a short integer id: only where it stands alone, never inside a status code
            text = re.sub(rf"(?<![\w.-]){re.escape(item)}(?![\w.-])", "<id>", text)
    # Content-Length is compared only where the body carries no per-request time and the ids are equally long.
    stable = all(len(item) == 36 for item in masked) and not _TIMESTAMP.search(response.text)
    headers = tuple((name, _EXPIRES.sub("expires=<time>", value))
                    for name, value in stable_headers(response, *long_ids))
    return (response.status_code, refusal_code(response), text, headers,
            response.headers.get("content-length") if stable else None,
            response.headers.get("x-chat-bootstrap-payload-bytes") if stable else None)


__all__ = ["ID_PARAMS", "NOT_WORKSPACE_ROWS", "WRITES_ON_READ", "Case", "UnexpectedAnswerError", "World", "answer",
           "case_urls", "id_cases", "list_routes", "platform_parents", "row_id", "seed", "unclassified_params",
           "unknown_like", "url", "world"]
