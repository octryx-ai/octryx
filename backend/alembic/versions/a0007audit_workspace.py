"""``audit_log.project_id``: the Workspace of an event about something that lives in one. Existing rows take it from
the row their resource id names, else from the Workspace id their details or request path recorded. A row of a kind
that always lives in a Workspace and stays unresolved keeps NULL, which no reader is shown."""

import json
import re
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a0007audit_workspace"
down_revision: str | None = "a0006runner_runtime"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_audit = sa.table("audit_log", sa.column("id", sa.String()), sa.column("resource_type", sa.String()),
                  sa.column("resource_id", sa.String()), sa.column("session_id", sa.String()),
                  sa.column("project_id", sa.String()),
                  sa.column("details", sa.JSON()))
# The kinds whose resource id is the Workspace itself.
_WORKSPACE_KINDS = ("workspace", "project", "project_config", "project_knowledge_mounts", "workspace_mcp_policy",
                    "code_style_workspace")
# {resource type: (table, Workspace column)} for a resource that is a row with its own Workspace column.
_OWN_COLUMN = {
    "agent_board_message": ("agent_board_message", "project_id"),
    "agent_definition": ("agent_definitions", "project_id"),
    "agent_presence": ("agent_presence", "project_id"),
    "budget_policy": ("budget_policies", "project_id"),
    "check_proposal": ("check_proposals", "workspace_id"),
    "code_repository": ("code_repositories", "project_id"),
    "code_style_repository": ("code_repositories", "project_id"),
    "connector_watcher": ("connector_watchers", "project_id"),
    "connector_watcher_rule": ("connector_watcher_rules", "project_id"),
    "database_connector": ("database_connectors", "project_id"),
    "device_job": ("device_jobs", "workspace_id"),
    "exec_policy_config": ("exec_policy_configs", "project_id"),
    "flow_definition": ("flow_definitions", "project_id"),
    "knowledge_memory_item": ("knowledge_memory_items", "project_id"),
    "knowledge_source_connector": ("knowledge_source_connectors", "project_id"),
    "model_policy": ("model_policies", "workspace_id"),
    "plugin_install": ("plugin_installs", "workspace_id"),
    "secure_work_coding_execution": ("work_items", "project_id"),
    "secure_work_coding_pipeline": ("work_items", "project_id"),
    "secure_work_pull_request": ("work_pull_requests", "scope_key"),
    "stored_secret": ("stored_secrets", "project_id"),
    "work_item": ("work_items", "project_id"),
    "work_item_claim": ("work_item_claim", "project_id"),
    "work_item_handoff_attachment": ("work_item_handoff_attachment", "project_id"),
    "work_item_sync_config": ("work_item_sync_configs", "project_id"),
    "work_item_takeover": ("work_item_takeover", "project_id"),
    "work_item_workflow": ("work_item_workflow_definitions", "project_id"),
    "workflow_run": ("workflow_runs", "project_id"),
}
# {resource type: (table, reference column, owner table, Workspace column)}: the Workspace of the row it references.
_THROUGH = {
    "documentation_write_intent": ("documentation_write_intents", "run_id", "workflow_runs", "project_id"),
    "flow_definition_version": ("flow_definition_versions", "flow_id", "flow_definitions", "project_id"),
    "secure_work_cicd": ("work_cicd_pipeline_traces", "work_item_id", "work_items", "project_id"),
    "secure_work_cicd_finding": ("work_cicd_findings", "work_item_id", "work_items", "project_id"),
}
# {resource type: whether the Workspace id leads (``<workspace>:<tool>``) or ends (``<connection>:<workspace>``) the
# resource id}.
_COMPOSITE_ID = {"workspace_connection": True, "connection_deviation": False}
_DETAIL_KEYS = ("workspace_id", "project_id")
_UUID = r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
# A generic request row's path names its Workspace as the route parameter after ``projects`` or ``workspaces``.
_WORKSPACE_PATH = re.compile(rf"/(?:projects|workspaces)/({_UUID})(?=/|$)")


def _fill(connection, resource_type: str, workspace) -> None:
    connection.execute(_audit.update().where(_audit.c.resource_type == resource_type, _audit.c.project_id.is_(None))
                       .values(project_id=workspace))


def _composite_workspace(projects, leading: bool):
    resource_id, width = _audit.c.resource_id, 36
    if leading:
        workspace, separator = sa.func.substr(resource_id, 1, width), sa.func.substr(resource_id, width + 1, 1)
    else:
        start = sa.func.length(resource_id) - width + 1
        workspace, separator = sa.func.substr(resource_id, start), sa.func.substr(resource_id, start - 1, 1)
    return sa.select(projects.c.id).where(projects.c.id == workspace, separator == ":").scalar_subquery()


def _column(table: str, name: str):
    return sa.table(table, sa.column("id", sa.String()), sa.column(name, sa.String()))


def _details(raw) -> dict:
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except ValueError:
            return {}
    return raw if isinstance(raw, dict) else {}


def _from_details(resource_type: str | None, details: dict) -> str | None:
    for key in _DETAIL_KEYS:
        value = details.get(key)
        if isinstance(value, str) and re.fullmatch(_UUID, value):
            return value
    if resource_type == "api":
        found = _WORKSPACE_PATH.search(str(details.get("path") or ""))
        return found.group(1) if found else None
    return None


def upgrade() -> None:
    with op.batch_alter_table("audit_log") as batch:
        batch.add_column(sa.Column("project_id", sa.String(length=36), nullable=True))
        batch.create_index(batch.f("ix_audit_log_project_id"), ["project_id"], unique=False)
    connection = op.get_bind()
    projects = sa.table("projects", sa.column("id", sa.String()))
    for kind in _WORKSPACE_KINDS:
        _fill(connection, kind, sa.select(projects.c.id).where(projects.c.id == _audit.c.resource_id)
              .scalar_subquery())
    for kind, (table, name) in _OWN_COLUMN.items():
        rows = _column(table, name)
        _fill(connection, kind, sa.select(rows.c[name]).where(rows.c.id == _audit.c.resource_id).scalar_subquery())
    for kind, (table, reference, owner_table, name) in _THROUGH.items():
        rows, owners = _column(table, reference), _column(owner_table, name)
        _fill(connection, kind, sa.select(owners.c[name]).where(
            owners.c.id == sa.select(rows.c[reference]).where(rows.c.id == _audit.c.resource_id).scalar_subquery())
            .scalar_subquery())
    for kind, leading in _COMPOSITE_ID.items():
        _fill(connection, kind, _composite_workspace(projects, leading))
    # A run's server command has no session to own it; its resource id is the run.
    runs = _column("workflow_runs", "project_id")
    connection.execute(_audit.update().where(_audit.c.resource_type == "server_command", _audit.c.session_id.is_(None),
                                             _audit.c.project_id.is_(None))
                       .values(project_id=sa.select(runs.c.project_id).where(runs.c.id == _audit.c.resource_id)
                               .scalar_subquery()))
    text = sa.cast(_audit.c.details, sa.Text())
    unresolved = connection.execute(sa.select(_audit.c.id, _audit.c.resource_type, _audit.c.details).where(
        _audit.c.project_id.is_(None),
        sa.or_(*(text.like(f'%"{key}"%') for key in _DETAIL_KEYS), text.like("%/projects/%"),
               text.like("%/workspaces/%")))).all()
    for row_id, resource_type, raw in unresolved:
        workspace = _from_details(resource_type, _details(raw))
        if workspace is not None:
            connection.execute(_audit.update().where(_audit.c.id == row_id).values(project_id=workspace))


def downgrade() -> None:
    with op.batch_alter_table("audit_log") as batch:
        batch.drop_index(batch.f("ix_audit_log_project_id"))
        batch.drop_column("project_id")
