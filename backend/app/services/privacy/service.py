from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import timedelta
from pathlib import Path

from fastapi import HTTPException
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ...models import (
    AgentTraceRun,
    AgentTraceSpan,
    AuditLog,
    DataExport,
    DeletionRequest,
    Message,
    Notification,
    RetentionPolicy,
    Session,
    SkillUsageEvent,
    TeamMember,
    ThreadContext,
    ToolCall,
    TurnTrace,
    TurnTraceSummary,
    UsageEvent,
    User,
    UserIdentity,
    UserInvitation,
    UserProject,
    UserRole,
)
from ...time_utils import utc_now
from ..artifact_store import (
    delete_tool_artifacts_for_sessions,
    delete_tool_artifacts_for_tool_call_ids,
)
from .observability_retention import OBSERVABILITY_RETENTION_ENTITIES, apply_observability_retention

logger = logging.getLogger(__name__)
WORKSPACE_ROOT = Path(__file__).resolve().parents[4]
EXPORT_DIR = WORKSPACE_ROOT / "data" / "exports"
SUPPORTED_RETENTION_ENTITIES = {
    "notifications",
    "audit_log",
    "usage_events",
    "skill_usage_events",
    "turn_traces",
    "tool_calls",
    "messages",
    "sessions",
    "agent_trace_runs",
    *OBSERVABILITY_RETENTION_ENTITIES,
}


async def upsert_retention_policy(db: AsyncSession, *, payload: dict) -> dict:
    entity_type = str(payload.get("entity_type") or "").strip().lower()
    action = str(payload.get("action") or "").strip().lower()
    ttl_days = int(payload.get("ttl_days") or 0)
    if entity_type not in SUPPORTED_RETENTION_ENTITIES:
        raise HTTPException(status_code=400, detail="Unsupported entity_type")
    if action not in {"delete", "anonymize"}:
        raise HTTPException(status_code=400, detail="Unsupported retention action")
    policy = (
        await db.execute(select(RetentionPolicy).where(RetentionPolicy.entity_type == entity_type))
    ).scalar_one_or_none()
    if policy is None:
        policy = RetentionPolicy(id=str(uuid.uuid4()), entity_type=entity_type)
        db.add(policy)
    policy.ttl_days = ttl_days
    policy.action = action
    policy.is_active = bool(payload.get("is_active", True))
    await db.commit()
    return serialize_retention_policy(policy)


def serialize_retention_policy(policy: RetentionPolicy) -> dict:
    return {
        "id": policy.id,
        "entity_type": policy.entity_type,
        "ttl_days": int(policy.ttl_days),
        "action": policy.action,
        "is_active": bool(policy.is_active),
    }


def serialize_deletion_request(row: DeletionRequest) -> dict:
    return {
        "id": row.id,
        "requested_by": row.requested_by,
        "target_user_id": row.target_user_id,
        "status": row.status,
        "reason": row.reason,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "completed_at": row.completed_at.isoformat() if row.completed_at else None,
    }


async def list_retention_policies(db: AsyncSession) -> list[dict]:
    rows = (await db.execute(select(RetentionPolicy).order_by(RetentionPolicy.entity_type.asc()))).scalars().all()
    return [serialize_retention_policy(row) for row in rows]


async def list_deletion_requests(db: AsyncSession) -> list[dict]:
    rows = (await db.execute(select(DeletionRequest).order_by(DeletionRequest.created_at.desc()))).scalars().all()
    return [serialize_deletion_request(row) for row in rows]


async def create_deletion_request(
    db: AsyncSession,
    *,
    requested_by: str,
    target_user_id: str,
    reason: str | None,
) -> dict:
    user = await db.get(User, target_user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="Target user not found")
    existing = (
        await db.execute(
            select(DeletionRequest).where(
                DeletionRequest.target_user_id == target_user_id,
                DeletionRequest.status == "pending",
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return serialize_deletion_request(existing)
    row = DeletionRequest(
        id=str(uuid.uuid4()),
        requested_by=requested_by,
        target_user_id=target_user_id,
        reason=(reason or "").strip() or None,
    )
    db.add(row)
    await db.commit()
    return serialize_deletion_request(row)


async def _export_user_data(
    db: AsyncSession,
    *,
    requested_by: str,
    target_user: User,
    export_dir: Path | None = None,
) -> DataExport:
    # Resolve at call time so a monkeypatched module-level EXPORT_DIR applies.
    export_dir = export_dir if export_dir is not None else EXPORT_DIR
    export_dir.mkdir(parents=True, exist_ok=True)
    export = DataExport(
        id=str(uuid.uuid4()),
        requested_by=requested_by,
        target_user_id=target_user.id,
        status="running",
    )
    db.add(export)
    await db.flush()

    sessions = (await db.execute(select(Session).where(Session.user_id == target_user.id))).scalars().all()
    notifications = (
        (await db.execute(select(Notification).where(Notification.user_id == target_user.id))).scalars().all()
    )
    memberships = (await db.execute(select(TeamMember).where(TeamMember.user_id == target_user.id))).scalars().all()
    projects = (await db.execute(select(UserProject).where(UserProject.user_id == target_user.id))).scalars().all()
    payload = {
        "user": {
            "id": target_user.id,
            "username": target_user.username,
            "email": target_user.email,
            "display_name": target_user.display_name,
            "auth_source": target_user.auth_source,
        },
        "session_ids": [session.id for session in sessions],
        "notifications": [
            {
                "id": row.id,
                "type": row.type,
                "title": row.title,
                "created_at": row.created_at.isoformat() if row.created_at else None,
            }
            for row in notifications
        ],
        "team_memberships": [{"team_id": row.team_id, "role": row.role} for row in memberships],
        "project_memberships": [{"project_id": row.project_id, "role": row.role} for row in projects],
    }
    file_path = export_dir / f"{export.id}.json"
    file_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    export.file_url = str(file_path)
    export.status = "completed"
    export.completed_at = utc_now()
    await db.flush()
    return export


async def _apply_user_deletion(db: AsyncSession, *, target_user: User) -> None:
    sessions = (await db.execute(select(Session.id).where(Session.user_id == target_user.id))).scalars().all()
    if sessions:
        await delete_tool_artifacts_for_sessions(db, list(sessions))
        await db.execute(delete(ThreadContext).where(ThreadContext.session_id.in_(sessions)))
        await db.execute(delete(ToolCall).where(ToolCall.session_id.in_(sessions)))
        await db.execute(delete(TurnTrace).where(TurnTrace.session_id.in_(sessions)))
        await db.execute(delete(UsageEvent).where(UsageEvent.session_id.in_(sessions)))
        await db.execute(delete(SkillUsageEvent).where(SkillUsageEvent.session_id.in_(sessions)))
        await db.execute(delete(Message).where(Message.session_id.in_(sessions)))
        await db.execute(delete(Session).where(Session.id.in_(sessions)))

    await db.execute(delete(Notification).where(Notification.user_id == target_user.id))
    await db.execute(delete(UserProject).where(UserProject.user_id == target_user.id))
    await db.execute(delete(TeamMember).where(TeamMember.user_id == target_user.id))
    await db.execute(delete(UserRole).where(UserRole.user_id == target_user.id))
    await db.execute(delete(UserIdentity).where(UserIdentity.user_id == target_user.id))
    await db.execute(delete(UserInvitation).where(UserInvitation.email == target_user.email))

    suffix = target_user.id.replace("-", "")[:8]
    target_user.username = f"deleted-user-{suffix}"
    target_user.email = f"deleted+{suffix}@local"
    target_user.display_name = "Deleted User"
    target_user.is_active = False


async def process_pending_deletion_requests(
    db: AsyncSession,
    *,
    export_user_data_func=None,
    apply_user_deletion_func=None,
) -> int:
    rows = (
        (
            await db.execute(
                select(DeletionRequest)
                .where(DeletionRequest.status == "pending")
                .order_by(DeletionRequest.created_at.asc())
            )
        )
        .scalars()
        .all()
    )
    processed = 0
    for row in rows:
        user = await db.get(User, row.target_user_id)
        if user is None:
            row.status = "failed"
            row.completed_at = utc_now()
            continue
        export_user_data = export_user_data_func or _export_user_data
        apply_user_deletion = apply_user_deletion_func or _apply_user_deletion
        await export_user_data(db, requested_by=row.requested_by, target_user=user)
        await apply_user_deletion(db, target_user=user)
        row.status = "completed"
        row.completed_at = utc_now()
        processed += 1
    if rows:
        await db.commit()
    return processed


async def apply_retention_policies(
    db: AsyncSession,
    *,
    delete_tool_artifacts_for_sessions_func=delete_tool_artifacts_for_sessions,
    delete_tool_artifacts_for_tool_call_ids_func=delete_tool_artifacts_for_tool_call_ids,
) -> int:
    rows = (await db.execute(select(RetentionPolicy).where(RetentionPolicy.is_active))).scalars().all()
    affected = 0
    now = utc_now()
    for row in rows:
        cutoff = now - timedelta(days=int(row.ttl_days))
        observability = await apply_observability_retention(db, entity_type=row.entity_type, cutoff=cutoff)
        if observability is not None:
            affected += observability
        elif row.entity_type == "notifications":
            result = await db.execute(delete(Notification).where(Notification.created_at < cutoff))
            affected += int(result.rowcount or 0)
        elif row.entity_type == "audit_log":
            result = await db.execute(delete(AuditLog).where(AuditLog.created_at < cutoff))
            affected += int(result.rowcount or 0)
        elif row.entity_type == "usage_events":
            result = await db.execute(delete(UsageEvent).where(UsageEvent.created_at < cutoff))
            affected += int(result.rowcount or 0)
        elif row.entity_type == "skill_usage_events":
            if row.action == "anonymize":
                trace_rows = (
                    (await db.execute(select(SkillUsageEvent).where(SkillUsageEvent.created_at < cutoff)))
                    .scalars()
                    .all()
                )
                for trace in trace_rows:
                    trace.query_excerpt = ""
                    trace.policy_reason = ""
                    trace.selection_reason = ""
                    trace.user_id = None
                    trace.session_id = None
                    trace.request_id = None
                    trace.event_metadata = {"retention": "anonymized"}
                affected += len(trace_rows)
            else:
                result = await db.execute(delete(SkillUsageEvent).where(SkillUsageEvent.created_at < cutoff))
                affected += int(result.rowcount or 0)
        elif row.entity_type == "turn_traces":
            old_traces = select(TurnTrace.id).where(TurnTrace.created_at < cutoff)
            await db.execute(delete(TurnTraceSummary).where(TurnTraceSummary.trace_id.in_(old_traces)))
            result = await db.execute(delete(TurnTrace).where(TurnTrace.created_at < cutoff))
            affected += int(result.rowcount or 0)
        elif row.entity_type == "agent_trace_runs":
            old_run_ids = (
                (await db.execute(select(AgentTraceRun.id).where(AgentTraceRun.created_at < cutoff))).scalars().all()
            )
            if row.action == "anonymize":
                span_rows = (
                    (await db.execute(select(AgentTraceSpan).where(AgentTraceSpan.trace_run_id.in_(old_run_ids))))
                    .scalars()
                    .all()
                )
                for span in span_rows:
                    span.input_json = {"retention": "anonymized"}
                    span.output_json = {"retention": "anonymized"}
                    span.span_metadata = {"retention": "anonymized"}
                    span.error = None
                run_rows = (
                    (await db.execute(select(AgentTraceRun).where(AgentTraceRun.id.in_(old_run_ids)))).scalars().all()
                )
                for run in run_rows:
                    run.session_id = None
                    run.message_id = None
                    run.trace_metadata = {"retention": "anonymized"}
                    run.error = None
                affected += len(run_rows) + len(span_rows)
            else:
                span_result = await db.execute(
                    delete(AgentTraceSpan).where(AgentTraceSpan.trace_run_id.in_(old_run_ids))
                )
                run_result = await db.execute(delete(AgentTraceRun).where(AgentTraceRun.id.in_(old_run_ids)))
                affected += int(span_result.rowcount or 0) + int(run_result.rowcount or 0)
        elif row.entity_type == "tool_calls":
            tool_call_ids = (await db.execute(select(ToolCall.id).where(ToolCall.created_at < cutoff))).scalars().all()
            await delete_tool_artifacts_for_tool_call_ids_func(db, list(tool_call_ids))
            result = await db.execute(delete(ToolCall).where(ToolCall.created_at < cutoff))
            affected += int(result.rowcount or 0)
        elif row.entity_type == "messages":
            if row.action == "anonymize":
                message_rows = (await db.execute(select(Message).where(Message.created_at < cutoff))).scalars().all()
                for message in message_rows:
                    message.content = "[redacted by retention policy]"
                    message.tool_calls = None
                    message.tool_results = None
                    message.model = None
                affected += len(message_rows)
            else:
                result = await db.execute(delete(Message).where(Message.created_at < cutoff))
                affected += int(result.rowcount or 0)
        elif row.entity_type == "sessions":
            if row.action == "anonymize":
                session_rows = (await db.execute(select(Session).where(Session.started_at < cutoff))).scalars().all()
                for session in session_rows:
                    session.metadata_ = {"retention": "anonymized"}
                    session.status = "archived"
                affected += len(session_rows)
            else:
                old_session_ids = (
                    (await db.execute(select(Session.id).where(Session.started_at < cutoff))).scalars().all()
                )
                await delete_tool_artifacts_for_sessions_func(db, list(old_session_ids))
                await db.execute(delete(SkillUsageEvent).where(SkillUsageEvent.session_id.in_(old_session_ids)))
                result = await db.execute(delete(Session).where(Session.started_at < cutoff))
                affected += int(result.rowcount or 0)
    if rows:
        await db.commit()
    return affected


class RetentionWorker:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]):
        self._session_factory = session_factory
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._run_loop())

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def run_once(self) -> None:
        async with self._session_factory() as db:
            await apply_retention_policies(db)
            await process_pending_deletion_requests(db)

    async def _run_loop(self) -> None:
        while True:
            try:
                await self.run_once()
            except Exception:
                logger.exception("Retention worker run failed")
            await asyncio.sleep(60 * 60 * 24)
