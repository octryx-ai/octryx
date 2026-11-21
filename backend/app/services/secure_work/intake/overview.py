"""The intake overview of one Workspace: every source with Connection · In Knowledge ·
In Work, and the Workspace's intakes.

Sources: the registered Work sources (``intake/registry``: Jira, ServiceNow, ...) always; a content-only source
(Confluence) only when the Workspace has a connection or a Knowledge source of it, and Custom REST only when the
Workspace has a REST API connection or an intake of it. Per source ``work_state`` is

- ``not_a_work_source``: content only, nothing flows into Work;
- ``no_connection``: the Workspace has no connection of it (set one up in Workspace → Connectors);
- ``no_intake``: connected, but nothing flows into Work yet;
- ``set_up``: at least one intake.

Only the caller's Workspace is read; configs of other Workspaces never appear.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ....models import WorkItem, WorkItemSyncConfig
from ....models.project.knowledge_source_sync import (
    RUN_STATE_COMPLETED,
    KnowledgeSourceConnector,
    KnowledgeSourceSyncRun,
)
from ...named_connections.contract import DEFAULT_CONNECTION_NAME
from ..jira_values import iso
from .connections import workspace_connections
from .registry import entry_of, source_for, source_types
from .schedule import schedule_of
from .setup import sync_mode_of

CONTENT_SOURCES = {"confluence": "Confluence"}

STATE_NOT_A_WORK_SOURCE = "not_a_work_source"
STATE_NO_CONNECTION = "no_connection"
STATE_NO_INTAKE = "no_intake"
STATE_SET_UP = "set_up"



def work_sources() -> dict[str, str]:
    """``source_type -> label`` of every registered Work source."""
    return {source_type: entry_of(source_type).label for source_type in source_types()}


async def _knowledge(db: AsyncSession, project_id: str, kind: str) -> dict[str, Any] | None:
    ids = list((await db.execute(select(KnowledgeSourceConnector.id).where(
        KnowledgeSourceConnector.project_id == project_id, KnowledgeSourceConnector.kind == kind))).scalars())
    if not ids:
        return None
    last = (await db.execute(select(func.max(KnowledgeSourceSyncRun.finished_at)).where(
        KnowledgeSourceSyncRun.connector_id.in_(ids), KnowledgeSourceSyncRun.state == RUN_STATE_COMPLETED))).scalar()
    return {"sources": len(ids), "last_synced_at": iso(last)}


async def _item_counts(db: AsyncSession, project_id: str) -> dict[str, int]:
    rows = await db.execute(
        select(WorkItem.sync_config_id, func.count()).where(WorkItem.project_id == project_id)
        .group_by(WorkItem.sync_config_id)
    )
    return {str(config_id): int(count) for config_id, count in rows.all() if config_id}


def _connection_ref(row: WorkItemSyncConfig, connections: list[dict[str, Any]]) -> dict[str, Any]:
    wanted = str(getattr(row, "connection_id", None) or row.connector_name or DEFAULT_CONNECTION_NAME)
    found = next((c for c in connections if wanted in (c["id"], c["name"], *c.get("aliases", ()))), None)
    if found is None:
        return {"id": wanted, "name": wanted, "available": False}
    return {"id": found["id"], "name": found["name"], "available": True}


def _what_value(value: Any) -> Any:
    """A list-valued field as a list; a scalar (Custom REST's ``operation``, ``role``) exactly as stored.

    ``list`` of every field would turn a REST intake's operation ``list_tickets`` into ``['l', 'i', 's', ...]``."""
    return list(value) if isinstance(value, (list, tuple)) else value


def _what(row: WorkItemSyncConfig) -> dict[str, Any]:
    stored = {**dict(row.filters_json or {}), **dict(row.field_mapping_json or {})}
    keys = tuple(getattr(source_for(row.source_type), "what_keys", ()) or ())
    what: dict[str, Any] = {key: _what_value(stored.get(key)) for key in keys}
    what["custom_query"] = bool(str(stored.get("jql") or stored.get("sysparm_query") or "").strip())
    return what


def describe_intake_row(row: WorkItemSyncConfig, connections: list[dict[str, Any]], items: int,
                        workflow_policy: Any = None) -> dict[str, Any]:
    """One intake of the overview; ``sync_mode`` is its own write-back mode (``None``: follows the workflow) and
    ``effective_sync_mode`` the one that decides, with the Workspace workflow's ``workflow_policy``."""
    options = dict(row.sync_options_json or {})
    modes = sync_mode_of(row, workflow_policy)
    return {
        "id": row.id,
        "name": row.name,
        "source_type": row.source_type,
        "is_active": bool(row.is_active),
        "connection": _connection_ref(row, connections),
        "what": _what(row),
        "schedule": schedule_of(options),
        "automation_mode": str(options.get("automation_mode") or "") or None,
        "automation_labels": list(options.get("automation_labels") or []),
        "sync_mode": modes["own"],
        "workflow_sync_mode": modes["workflow"],
        "effective_sync_mode": modes["effective"],
        "items": items,
        "last_run_at": iso(row.last_sync_at),
        "last_run_status": row.last_sync_status,
    }


async def intake_overview(db: AsyncSession, project_id: str) -> dict[str, Any]:
    configs = list((await db.execute(
        select(WorkItemSyncConfig).where(WorkItemSyncConfig.project_id == project_id)
        .order_by(WorkItemSyncConfig.created_at)
    )).scalars())
    counts = await _item_counts(db, project_id)
    from ..lifecycle_transitions import default_workflow_for_item

    workflow = await default_workflow_for_item(db, WorkItem(project_id=project_id))
    policy = workflow.sync_policy_json if workflow is not None else None
    sources: list[dict[str, Any]] = []
    intakes: list[dict[str, Any]] = []
    work = work_sources()
    for kind, label in {**work, **CONTENT_SOURCES}.items():
        listed_by = getattr(source_for(kind), "workspace_connections", None)
        if listed_by is not None:  # a source with its own connections (Custom REST: its REST definitions)
            connections = await listed_by(db, project_id)
        else:
            connections = await workspace_connections(db, project_id, kind)
        knowledge = await _knowledge(db, project_id, kind)
        work_capable = kind in work
        if not work_capable and not connections and knowledge is None:
            continue
        own = [row for row in configs if row.source_type == kind]
        if listed_by is not None and not connections and not own:
            continue  # a source with its own connections (Custom REST) shows only where the Workspace has one
        described = [describe_intake_row(row, connections, counts.get(row.id, 0), policy) for row in own]
        intakes.extend(described)
        in_work = None
        if described:
            runs = [entry for entry in described if entry["last_run_at"]]
            last = max(runs, key=lambda entry: entry["last_run_at"]) if runs else None
            in_work = {"intakes": len(described), "active": sum(1 for entry in described if entry["is_active"]),
                    "items": sum(entry["items"] for entry in described),
                    "last_run_at": last["last_run_at"] if last else None,
                    "last_run_status": last["last_run_status"] if last else None}
        if not work_capable:
            state = STATE_NOT_A_WORK_SOURCE
        elif described:
            state = STATE_SET_UP
        elif not connections:
            state = STATE_NO_CONNECTION
        else:
            state = STATE_NO_INTAKE
        sources.append({"kind": kind, "label": label, "work_capable": work_capable,
                        "connections": [{key: entry[key] for key in ("id", "name", "scope")} for entry in connections],
                        "knowledge": knowledge, "work": in_work, "work_state": state})
    return {"project_id": project_id, "sources": sources, "intakes": intakes}


__all__ = [
    "STATE_NOT_A_WORK_SOURCE",
    "STATE_NO_CONNECTION",
    "STATE_NO_INTAKE",
    "STATE_SET_UP",
    "describe_intake_row",
    "intake_overview",
]
