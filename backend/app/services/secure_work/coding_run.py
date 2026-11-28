"""Runtime envelope for scheduled coding-delivery agent runs (execution mode ``coding_delivery``)."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import Task, TaskRun, User, WorkItem
from ...time_utils import utc_now
from ..agent_definition_payload import CODING_DELIVERY_EXECUTION_MODE
from .platform_items import create_platform_work_item

logger = logging.getLogger(__name__)

_RUN_SOURCE_ID_PREFIX = "task:"
_MAX_RUN_SESSIONS = 50


def is_coding_delivery_agent(agent_definition: dict[str, Any] | None) -> bool:
    # The mode is configuration on the definition; the agent's name decides nothing.
    return str((agent_definition or {}).get("executionMode") or "").strip() == CODING_DELIVERY_EXECUTION_MODE


async def _find_run_work_item(db: AsyncSession, *, task_id: str) -> WorkItem | None:
    # Bound to its task via ``source_id`` for idempotency.
    return (
        await db.execute(
            select(WorkItem)
            .where(
                WorkItem.source_type == "platform",
                WorkItem.source_id == f"{_RUN_SOURCE_ID_PREFIX}{task_id}",
            )
            .order_by(WorkItem.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


def _clarification_context(item: WorkItem) -> dict[str, Any]:
    fields = item.source_fields_json if isinstance(item.source_fields_json, dict) else {}
    gate = fields.get("clarification") if isinstance(fields.get("clarification"), dict) else {}
    return {
        "work_item_id": item.id,
        "source_key": item.source_key,
        "clarification_state": str(fields.get("clarification_state") or "not_required"),
        "clarification": gate,
    }


async def ensure_coding_run_work_item(
    db: AsyncSession,
    *,
    task: Task,
    task_run: TaskRun,
    agent_definition: dict[str, Any] | None,
    prompt: str,
    trigger_type: str,
) -> dict[str, Any] | None:
    # Best effort: a scheduling run must never crash on the governance envelope.
    if not is_coding_delivery_agent(agent_definition):
        return None
    if not task.project_id:
        return None

    owner = await db.get(User, task.owner_id)
    if owner is None:
        return None

    item = await _find_run_work_item(db, task_id=task.id)
    if item is None:
        try:
            item = await create_platform_work_item(
                db,
                current_user=owner,
                project_id=task.project_id,
                title=task.name,
                description=prompt or task.description or "",
                issue_type="task",
            )
        except HTTPException as exc:
            logger.warning("coding_run.work_item_create_skipped task=%s detail=%s", task.id, exc.detail)
            return None
        item.source_id = f"{_RUN_SOURCE_ID_PREFIX}{task.id}"
        fields = dict(item.source_fields_json or {})
        fields["coding_run"] = {
            "task_id": task.id,
            "task_run_id": task_run.id,
            "agent_definition_id": str((agent_definition or {}).get("id") or ""),
            "trigger_type": trigger_type,
        }
        item.source_fields_json = fields

    gate = await definition_of_ready_gate(db, item)
    fields = dict(item.source_fields_json or {})
    fields["clarification"] = gate
    fields["clarification_state"] = "resolved" if gate["readiness"] == "ready" else "needed"
    item.source_fields_json = fields
    item.updated_at = utc_now()
    await db.flush()
    return _clarification_context(item)


async def definition_of_ready_gate(db: AsyncSession, item: WorkItem) -> dict[str, Any]:
    # Ready only after a confirmed Definition of Ready, never guessed from text.
    from ..workflow_runs.definition_of_ready import TRIAGE_WORKFLOW_KEY, confirmed_ready

    if await confirmed_ready(db, item.id):
        return {"readiness": "ready", "source": "definition_of_ready", "questions": []}
    return {
        "readiness": "blocked",
        "source": "definition_of_ready",
        "questions": [{
            "dimension": "definition_of_ready",
            "question": f"Triage {item.source_key} with the '{TRIAGE_WORKFLOW_KEY}' workflow and confirm it is "
                        "ready before code changes.",
            "severity": "high",
            "status": "open",
        }],
    }


async def link_coding_run_session(
    db: AsyncSession,
    *,
    work_item_id: str,
    session_id: str,
    task_run_id: str,
) -> None:
    item = await db.get(WorkItem, work_item_id)
    if item is None:
        return
    fields = dict(item.source_fields_json or {})
    sessions = [entry for entry in fields.get("coding_run_sessions") or [] if isinstance(entry, dict)]
    if not any(entry.get("session_id") == session_id for entry in sessions):
        sessions.append(
            {"session_id": session_id, "task_run_id": task_run_id, "linked_at": utc_now().isoformat()}
        )
        fields["coding_run_sessions"] = sessions[-_MAX_RUN_SESSIONS:]
        item.source_fields_json = fields
        item.updated_at = utc_now()
        await db.flush()


__all__ = [
    "ensure_coding_run_work_item",
    "is_coding_delivery_agent",
    "link_coding_run_session",
]
