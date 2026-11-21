"""Real resource rows of a conflicting Workspace for the generated Workspace route test.

A route that takes a Workspace id and the id of another resource must answer a real resource of a different
Workspace exactly like a resource that does not exist. :data:`RESOURCE_ROWS` names, per path parameter, the model of
the resource it addresses, and :data:`REQUEST_REFERENCES` the body and query fields a guarded route family reads (the Secure Work families: items, intake, workflows, change plans, pull requests, coding
pipelines and runs; connector watchers and rules; Work-role assignments). :func:`seed_resource` creates such a row
bound to a given Workspace: every required column gets a synthetic value carrying the marker the answer must never
show, a Workspace column the given Workspace, a user column the given user, and a required (or Work item) parent
row is created the same way, so the row is bound to the Workspace through its parent too.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, Integer, Numeric, String, Text

from app.db import Base
from app.models import ConnectorWatcher, ConnectorWatcherRule
from app.models.runtime.secure_work import (
    WorkChangePlan,
    WorkCodingPipelineConfig,
    WorkCodingPipelineRun,
    WorkItem,
    WorkItemChangeUnit,
    WorkItemSyncConfig,
    WorkItemWorkflowDefinition,
    WorkPullRequest,
)
from app.models.runtime.work_role_model import WorkRoleAssignment
from app.time_utils import utc_now

WORKSPACE_COLUMNS = frozenset({"project_id", "workspace_id", "scope_key"})
# A parent a resource is bound to its Workspace through, created even where the column is optional.
BINDING_PARENTS = frozenset({"work_items"})


@dataclass(frozen=True)
class ResourceRow:
    param: str
    model: type
    path: re.Pattern[str] = re.compile("")
    # Columns a check constraint ties together, set explicitly.
    values: tuple[tuple[str, Any], ...] = ()
    # The request methods a request field is read on (empty: every method).
    methods: frozenset[str] = frozenset()


RESOURCE_ROWS: tuple[ResourceRow, ...] = (
    ResourceRow("work_item_id", WorkItem),
    ResourceRow("intake_id", WorkItemSyncConfig),
    ResourceRow("workflow_id", WorkItemWorkflowDefinition, re.compile(r"^/api/v1/secure-work/workflows/")),
    ResourceRow("change_plan_id", WorkChangePlan),
    ResourceRow("pull_request_id", WorkPullRequest),
    ResourceRow("config_id", WorkCodingPipelineConfig, re.compile(r"/coding-pipelines/")),
    ResourceRow("run_id", WorkCodingPipelineRun, re.compile(r"/coding-pipeline-runs/")),
    ResourceRow("watcher_id", ConnectorWatcher),
    ResourceRow("rule_id", ConnectorWatcherRule, re.compile(r"^/api/v1/connector-watchers/rules/")),
    ResourceRow("assignment_id", WorkRoleAssignment, values=(("subject_kind", "sso_group"),)),
)


def resource_rows_of(path: str, params: list[str]) -> list[ResourceRow]:
    return [row for row in RESOURCE_ROWS if row.param in params and row.path.search(path)]


def _secure_work_references() -> tuple[ResourceRow, ...]:
    """The related-resource fields of Secure Work requests (body of a write, query of a read): the Work Item and the
    change unit on every route (the scope dependency's addressed records), and the fields a handler loads through the
    scoped loader (``services/secure_work/related_rows.py``) on the routes whose handler reads them."""
    from app.services.secure_work.related_rows import CICD_PROVIDER, PIPELINE_CONFIG, PIPELINE_TRACE, REPOSITORY_PROFILE

    post = frozenset({"POST"})
    start = re.compile(r"/work-items/\{work_item_id\}/coding-(pipeline|agent)/start$")
    traces = re.compile(r"/work-items/\{work_item_id\}/cicd-pipeline-traces$")
    findings = re.compile(r"/work-items/\{work_item_id\}/cicd-findings$")
    return (
        ResourceRow("work_item_id", WorkItem), ResourceRow("change_unit_id", WorkItemChangeUnit),
        ResourceRow("config_id", PIPELINE_CONFIG.model, start, methods=post),
        ResourceRow("provider_config_id", CICD_PROVIDER.model, traces, methods=post),
        ResourceRow("provider_config_id", CICD_PROVIDER.model, findings, methods=post),
        ResourceRow("repository_profile_id", REPOSITORY_PROFILE.model, traces, methods=post),
        ResourceRow("pipeline_trace_id", PIPELINE_TRACE.model, findings, methods=post),
        ResourceRow("cicd_pipeline_trace_id", PIPELINE_TRACE.model, findings, methods=post),
    )


# The request fields naming a related resource, per guarded route family (by its scope dependency).
REQUEST_REFERENCES = {"app.api.routes._secure_work_scope.require_secure_work_scope": _secure_work_references}


def reference_rows_of(dependencies: tuple[str, ...], method: str, path: str) -> list[ResourceRow]:
    """The related-resource request fields the route ``method path`` of a guarded family (``dependencies``, qualified
    names) reads."""
    return [row for name in dependencies if name in REQUEST_REFERENCES for row in REQUEST_REFERENCES[name]()
            if row.path.search(path) and (not row.methods or method in row.methods)]


def _models_by_table() -> dict[str, type]:
    return {mapper.class_.__tablename__: mapper.class_ for mapper in Base.registry.mappers}


def _value(column: Any, marker: str) -> Any:
    kind = column.type
    if isinstance(kind, JSON):
        return {}
    if isinstance(kind, Boolean):
        return False
    if isinstance(kind, DateTime):
        return utc_now()
    if isinstance(kind, Integer | Numeric):
        return 1
    if isinstance(kind, String | Text):
        text = f"{marker}-{uuid.uuid4().hex[:8]}"
        length = getattr(kind, "length", None)
        return text[:length] if length else text
    raise TypeError(f"no synthetic value for {column}")


async def seed_resource(db, model: type, *, workspace_id: str, user_id: str, marker: str,
                        values: tuple[tuple[str, Any], ...] = ()) -> str:
    """A row of ``model`` bound to ``workspace_id`` (and its parents, see the module doc) with ``values`` set as
    given; its id."""
    tables = _models_by_table()
    fixed = dict(values)
    values = {}
    for column in model.__table__.columns:
        if column.primary_key:
            continue
        if column.name in fixed:
            values[column.name] = fixed[column.name]
            continue
        foreign = next(iter(column.foreign_keys), None)
        target = foreign.column.table.name if foreign is not None else None
        if column.name in WORKSPACE_COLUMNS and target in (None, "projects"):
            values[column.name] = workspace_id
        elif target == "users":
            if not column.nullable:
                values[column.name] = user_id
        elif target is not None:
            if not column.nullable or target in BINDING_PARENTS:
                values[column.name] = await seed_resource(db, tables[target], workspace_id=workspace_id,
                                                          user_id=user_id, marker=marker)
        elif not column.nullable and column.default is None and column.server_default is None:
            values[column.name] = _value(column, marker)
    if "claim_value" in model.__table__.columns and values.get("subject_kind") in ("sso_group", "sso_role"):
        values["claim_value"] = values["subject_key"]
    row = model(**values)
    db.add(row)
    await db.flush()
    return str(row.id)


__all__ = ["RESOURCE_ROWS", "ResourceRow", "resource_rows_of", "seed_resource"]
