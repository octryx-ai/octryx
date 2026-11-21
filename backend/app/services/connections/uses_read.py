"""Where a connection is used (the detail's ``uses``): Knowledge sources and intakes that name it by ``connection_id``.

- **knowledge**: ``knowledge_source_connectors.connection_id``; per source its Workspace, enabled (``state`` active),
  scope (the type's scope key), schedule (the shared list, ``schedules.py``), last run and ingested item count.
- **tickets**: ``work_item_sync_configs.connection_id``; per intake its Workspace, enabled, filter, schedule, status
  map (read through the intake's own draft, ``secure_work/intake/setup.draft_of``), last sync; write-back is the
  Workspace's work item workflow (``sync_policy.sync_mode`` ``execute``, transitions from its mappings).
- **agent_tools**: the connection's level and the tools its type routes.

Only ids, names, keys, states and times are read; never a config value of the source system or a secret.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import ConnectorNamedConnection, WorkItem, WorkItemSyncConfig
from ...models.project.knowledge_source_sync import (
    CONNECTOR_STATE_ACTIVE,
    ITEM_STATE_INGESTED,
    KnowledgeSourceConnector,
    KnowledgeSourceSyncItem,
    KnowledgeSourceSyncRun,
)
from ...time_utils import ensure_utc
from ..named_connections.connection_gate import is_write_tool
from ..named_connections.descriptors import routed_tool_names
from . import schedules
from .catalog import KNOWLEDGE_SCOPE_FIELDS, SCOPE_KEYS, TICKET_SCOPE_FIELDS, uses_of
from .contract import USE_AGENT_TOOLS, USE_KNOWLEDGE, USE_REPOSITORIES, USE_TICKETS


def iso(value: Any) -> str | None:
    normalized = ensure_utc(value)
    return normalized.isoformat() if normalized is not None else None


async def knowledge_rows(db: AsyncSession, ids: Iterable[str]) -> dict[str, list[KnowledgeSourceConnector]]:
    wanted = list(set(ids))
    found: dict[str, list[KnowledgeSourceConnector]] = {connection_id: [] for connection_id in wanted}
    if wanted:
        rows = await db.execute(select(KnowledgeSourceConnector).where(
            KnowledgeSourceConnector.connection_id.in_(wanted)).order_by(KnowledgeSourceConnector.connector_key))
        for row in rows.scalars().all():
            found[str(row.connection_id)].append(row)
    return found


async def intake_rows(db: AsyncSession, ids: Iterable[str]) -> dict[str, list[WorkItemSyncConfig]]:
    wanted = list(set(ids))
    found: dict[str, list[WorkItemSyncConfig]] = {connection_id: [] for connection_id in wanted}
    if wanted:
        rows = await db.execute(select(WorkItemSyncConfig).where(WorkItemSyncConfig.connection_id.in_(wanted))
                                .order_by(WorkItemSyncConfig.name))
        for row in rows.scalars().all():
            found[str(row.connection_id)].append(row)
    return found


def knowledge_scope(connection_type: str, row: KnowledgeSourceConnector) -> dict[str, list[str]] | None:
    key, field = SCOPE_KEYS.get(connection_type), KNOWLEDGE_SCOPE_FIELDS.get(connection_type)
    if key is None or field is None:
        return None
    return {key: [str(item) for item in (row.scope or {}).get(field) or ()]}


async def _last_runs(db: AsyncSession, ids: list[str]) -> dict[str, KnowledgeSourceSyncRun]:
    if not ids:
        return {}
    rows = (await db.execute(select(KnowledgeSourceSyncRun).where(KnowledgeSourceSyncRun.connector_id.in_(ids))
                             .order_by(KnowledgeSourceSyncRun.started_at.desc()))).scalars().all()
    latest: dict[str, KnowledgeSourceSyncRun] = {}
    for run in rows:
        latest.setdefault(str(run.connector_id), run)
    return latest


async def _item_counts(db: AsyncSession, ids: list[str]) -> dict[str, int]:
    if not ids:
        return {}
    rows = await db.execute(select(KnowledgeSourceSyncItem.connector_id, func.count())
                            .where(KnowledgeSourceSyncItem.connector_id.in_(ids),
                                   KnowledgeSourceSyncItem.state == ITEM_STATE_INGESTED)
                            .group_by(KnowledgeSourceSyncItem.connector_id))
    return {str(connector_id): int(count) for connector_id, count in rows.all()}


async def knowledge_use(db: AsyncSession, connection_type: str, rows: list[KnowledgeSourceConnector],
                        names: dict[str, str]) -> dict[str, Any]:
    ids = [row.id for row in rows]
    runs, counts = await _last_runs(db, ids), await _item_counts(db, ids)
    sources = []
    for row in rows:
        run = runs.get(row.id)
        sources.append({
            "connector_id": row.id, "connector_key": row.connector_key,
            "workspace": {"id": row.project_id, "name": names.get(row.project_id, row.project_id)},
            "enabled": row.state == CONNECTOR_STATE_ACTIVE, "scope": knowledge_scope(connection_type, row),
            **schedules.from_knowledge(bool(row.schedule_enabled), row.schedule_interval_minutes),
            "last_sync_at": iso(run.finished_at or run.started_at) if run else None,
            "last_sync_state": run.state if run else None, "items": counts.get(row.id, 0),
        })
    single = sources[0] if len(sources) == 1 else None
    latest = max((source for source in sources if source["last_sync_at"]), key=lambda s: s["last_sync_at"],
                 default=None)
    return {
        "enabled": any(source["enabled"] for source in sources),
        "scope": single["scope"] if single else None,
        "schedule": single["schedule"] if single else None,
        "schedule_cron": single["schedule_cron"] if single else None,
        "last_sync_at": latest["last_sync_at"] if latest else None,
        "last_sync_state": latest["last_sync_state"] if latest else None,
        "items": sum(source["items"] for source in sources),
        "sources": sources,
    }


async def write_back_of(db: AsyncSession, workspace_id: str | None, source_mode: str = "") -> dict[str, Any]:
    """The Workspace's work item workflow: write-back on (``execute``) and its transitions. ``source_mode`` is the
    intake's own ``sync_mode``: it overrides the workflow's default (``sync_policy``)."""
    from ..secure_work.lifecycle_transitions import default_workflow_for_item
    from ..secure_work.sync_policy import executes, mapped_status, mapped_transition

    workflow = await default_workflow_for_item(db, WorkItem(project_id=workspace_id))
    if workflow is None:
        return {"enabled": False, "transitions": []}
    enabled = executes(workflow.sync_policy_json, source_mode=source_mode)
    transitions = [
        {"ours": str(key), "source": str(mapped_transition(entry) or mapped_status(entry))}
        for key, entry in sorted((workflow.mappings_json or {}).items())
        if isinstance(entry, dict) and entry.get("sync_back")
        and (mapped_transition(entry) or mapped_status(entry))
    ]
    return {"enabled": enabled, "transitions": transitions}


def intake_entry(connection_type: str, row: WorkItemSyncConfig, names: dict[str, str]) -> dict[str, Any]:
    from ..secure_work.intake.setup import draft_of

    draft = draft_of(row)
    what = draft["what"]
    key, field = SCOPE_KEYS.get(connection_type), TICKET_SCOPE_FIELDS.get(connection_type)
    return {
        "intake_id": row.id, "name": row.name,
        "workspace": {"id": row.project_id, "name": names.get(row.project_id or "", row.project_id)},
        "enabled": bool(row.is_active),
        "filter": what.get("jql") if "jql" in what else what.get("sysparm_query"),
        "scope": {key: list(what.get(field) or [])} if key and field else None,
        **schedules.from_intake(draft["schedule"]),
        "status_map": [{"source": source, "ours": ours}
                       for source, ours in sorted(draft["how"]["status_mapping"].items())],
        "last_sync_at": iso(row.last_sync_at), "last_sync_status": row.last_sync_status,
    }


async def tickets_use(db: AsyncSession, connection_type: str, rows: list[WorkItemSyncConfig],
                      names: dict[str, str]) -> dict[str, Any]:
    from ..secure_work.sync_policy import intake_sync_mode

    intakes = [intake_entry(connection_type, row, names) for row in rows]
    single = intakes[0] if len(intakes) == 1 else None
    write_back = (await write_back_of(db, single["workspace"]["id"], intake_sync_mode(rows[0].sync_options_json))
                  if single else {"enabled": False, "transitions": []})
    return {
        "enabled": any(intake["enabled"] for intake in intakes),
        "filter": single["filter"] if single else None,
        "scope": single["scope"] if single else None,
        "schedule": single["schedule"] if single else None,
        "schedule_cron": single["schedule_cron"] if single else None,
        "status_map": single["status_map"] if single else [],
        "write_back": write_back,
        "intakes": [{key: intake[key] for key in ("intake_id", "name", "workspace", "enabled", "schedule",
                                                  "schedule_cron", "last_sync_at", "last_sync_status")}
                    for intake in intakes],
    }


def agent_tools_use(row: ConnectorNamedConnection) -> dict[str, Any]:
    # Each tool says whether it reads or writes, by the same classification the runtime gate uses.
    return {"level": row.agent_tools_level, "needs_approval": [],
            "tools": [{"name": name, "level": "write" if is_write_tool(name) else "read"}
                      for name in sorted(routed_tool_names(str(row.tool_name)))]}


async def uses_of_row(db: AsyncSession, row: ConnectorNamedConnection, knowledge: list[KnowledgeSourceConnector],
                      intakes: list[WorkItemSyncConfig], names: dict[str, str]) -> dict[str, Any]:
    kinds = uses_of(str(row.tool_name))
    uses: dict[str, Any] = {}
    if USE_KNOWLEDGE in kinds:
        uses[USE_KNOWLEDGE] = await knowledge_use(db, str(row.tool_name), knowledge, names)
    if USE_TICKETS in kinds:
        uses[USE_TICKETS] = await tickets_use(db, str(row.tool_name), intakes, names)
    if USE_AGENT_TOOLS in kinds:
        uses[USE_AGENT_TOOLS] = agent_tools_use(row)
    if USE_REPOSITORIES in kinds:
        uses[USE_REPOSITORIES] = []  # code repositories carry no connection reference yet (E6)
    return uses


def uses_summary(row: ConnectorNamedConnection, knowledge: list, intakes: list) -> dict[str, Any]:
    """The list's short form: ``{knowledge: bool, tickets: bool, agent_tools: level}``."""
    kinds = uses_of(str(row.tool_name))
    summary: dict[str, Any] = {}
    if USE_KNOWLEDGE in kinds:
        summary[USE_KNOWLEDGE] = any(item.state == CONNECTOR_STATE_ACTIVE for item in knowledge)
    if USE_TICKETS in kinds:
        summary[USE_TICKETS] = any(bool(item.is_active) for item in intakes)
    if USE_AGENT_TOOLS in kinds:
        summary[USE_AGENT_TOOLS] = row.agent_tools_level
    return summary


__all__ = [
    "intake_rows",
    "iso",
    "knowledge_rows",
    "knowledge_scope",
    "uses_of_row",
    "uses_summary",
    "write_back_of",
]
