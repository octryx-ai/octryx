"""A connection's recent errors and what still uses it (``recent_errors`` of the detail, the ``409`` of ``DELETE``)."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import ConnectorNamedConnection, WorkItemSyncConfig, WorkItemSyncRun
from ...models.agent.skill_catalog import SkillSource
from ...models.project.knowledge_source_sync import (
    RUN_STATE_FAILED,
    RUN_STATE_NEEDS_CONFIGURATION,
    KnowledgeSourceConnector,
    KnowledgeSourceSyncRun,
)
from .contract import USE_KNOWLEDGE, USE_TICKETS
from .error_sentences import RUNTIME_SENTENCES, sentence
from .uses_read import iso

MAX_ERRORS = 10
CODE_UNAUTHORIZED = "source_unauthorized"
MESSAGE_CHARS = 300


def _entry(at: Any, use: str, code: Any) -> dict[str, Any]:
    text = " ".join(str(code or "").split())[:MESSAGE_CHARS] or "unknown"
    return {"at": iso(at), "use": use, "code": text, "message": sentence(text, use)}


async def recent_errors(db: AsyncSession, row: ConnectorNamedConnection, knowledge: list[KnowledgeSourceConnector],
                        intakes: list[WorkItemSyncConfig]) -> list[dict[str, Any]]:
    errors: list[dict[str, Any]] = []
    if knowledge:
        runs = (await db.execute(select(KnowledgeSourceSyncRun).where(
            KnowledgeSourceSyncRun.connector_id.in_([item.id for item in knowledge]),
            KnowledgeSourceSyncRun.state.in_((RUN_STATE_FAILED, RUN_STATE_NEEDS_CONFIGURATION)),
        ).order_by(KnowledgeSourceSyncRun.started_at.desc()).limit(MAX_ERRORS))).scalars().all()
        errors += [_entry(run.finished_at or run.started_at, USE_KNOWLEDGE, run.reason or run.state) for run in runs]
    if intakes:
        runs = (await db.execute(select(WorkItemSyncRun).where(
            WorkItemSyncRun.sync_config_id.in_([item.id for item in intakes]), WorkItemSyncRun.error.is_not(None),
        ).order_by(WorkItemSyncRun.created_at.desc()).limit(MAX_ERRORS))).scalars().all()
        errors += [_entry(run.completed_at or run.created_at, USE_TICKETS, run.error) for run in runs]
    runtime_use = next((use for use, text in RUNTIME_SENTENCES.items() if text == row.state_reason), None)
    if row.state == "failing" and runtime_use is not None:  # a runtime use refused as unauthenticated
        errors.append({"at": iso(row.updated_at), "use": runtime_use, "code": CODE_UNAUTHORIZED,
                       "message": row.state_reason})
    errors.sort(key=lambda item: item["at"] or "", reverse=True)
    return errors[:MAX_ERRORS]


async def in_use(db: AsyncSession, row: ConnectorNamedConnection) -> list[dict[str, Any]]:
    users: list[dict[str, Any]] = []
    sources = (await db.execute(select(KnowledgeSourceConnector).where(
        KnowledgeSourceConnector.kind == row.tool_name))).scalars().all()
    for source in sources:
        if source.connection_id == row.id or (source.scope or {}).get("connection_id") == row.id:
            users.append({"use": USE_KNOWLEDGE, "id": source.id, "name": source.connector_key,
                          "workspace_id": source.project_id})
    intakes = (await db.execute(select(WorkItemSyncConfig).where(WorkItemSyncConfig.connection_id == row.id))).scalars()
    users += [{"use": USE_TICKETS, "id": intake.id, "name": intake.name, "workspace_id": intake.project_id}
              for intake in intakes]
    skills = (await db.execute(select(SkillSource).where(SkillSource.named_connection_id == row.id))).scalars()
    users += [{"use": "skills", "id": skill.id, "name": skill.label, "workspace_id": None} for skill in skills]
    return users


__all__ = ["MAX_ERRORS", "in_use", "recent_errors"]
