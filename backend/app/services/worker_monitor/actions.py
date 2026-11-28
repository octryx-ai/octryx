from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import Awaitable, Callable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.services.worker_monitor.common import _normalize_action

from ...models import AgentWorker, Role, Session, User, UserRole, WorkerMonitor
from ...services.content_security.untrusted_fence import untrusted_section
from ...services.outbound_webhook import emit_outbound_webhook_event
from ...services.run_capability.worker_profiles import worker_session_capability_metadata
from ...services.team_notification import create_notification
from ...services.worker import record_worker_trust_event
from ...services.worker.policy import can_worker_execute_action
from ...services.worker_escalation import log_worker_escalation

logger = logging.getLogger(__name__)

MonitorAgentRunner = Callable[..., Awaitable[None]]


async def _run_monitor_agent_session(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    session_id: str,
    prompt: str,
    user_id: str,
    project_id: str | None,
    agent_type: str,
) -> None:
    # The monitor's prompt is the session's runner turn (stored as its user message).
    from ..devices.agent_runtime import runner_turn

    async with session_factory() as db:
        try:
            await runner_turn(db, user_id=user_id, prompt=prompt, session_id=session_id)
        except Exception:
            logger.exception(
                "Worker monitor agent session failed",
                extra={"session_id": session_id, "agent_type": agent_type},
            )


async def _resolve_action_targets(db: AsyncSession, worker: AgentWorker) -> list[User]:
    if worker.escalation_user_id:
        user = await db.get(User, worker.escalation_user_id)
        return [user] if user else []
    users = (
        (
            await db.execute(
                select(User)
                .join(UserRole, UserRole.user_id == User.id)
                .join(Role, Role.id == UserRole.role_id)
                .where(Role.name == "admin")
                .order_by(User.created_at.asc())
            )
        )
        .scalars()
        .all()
    )
    return list(users)


async def _create_monitor_session(
    db: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    *,
    worker: AgentWorker,
    monitor: WorkerMonitor,
    severity: str,
    detected_value: str,
    action: str,
    run_monitor_agent_session: MonitorAgentRunner,
) -> str | None:
    targets = await _resolve_action_targets(db, worker)
    actor = targets[0] if targets else None
    if actor is None:
        return None
    prompt = (
        f"Worker monitor '{monitor.name}' triggered with severity '{severity}'. "
        f"Monitor type: {monitor.monitor_type}.\n"
        f"{untrusted_section('detected value', detected_value, source='the monitored system')}\n"
        "Investigate and respond with a concise summary."
    )
    if action == "auto_fix":
        prompt += " If the remediation is safe and policy-compliant, attempt an autonomous fix."
    session = Session(
        id=str(uuid.uuid4()),
        user_id=actor.id,
        project_id=worker.project_id,
        agent_type="change" if action == "auto_fix" else "diagnosis",
        status="active",
        origin="worker",
        metadata_={
            "worker_id": worker.id,
            "worker_monitor_id": monitor.id,
            "triggered_by": "worker_monitor",
            "triggered_action": action,
            **worker_session_capability_metadata("worker_monitor_action"),
        },
    )
    db.add(session)
    await db.flush()
    asyncio.create_task(
        run_monitor_agent_session(
            session_factory,
            session_id=session.id,
            prompt=prompt,
            user_id=actor.id,
            project_id=worker.project_id,
            agent_type=session.agent_type,
        )
    )
    return session.id


async def _apply_monitor_action(
    db: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    *,
    worker: AgentWorker,
    monitor: WorkerMonitor,
    severity: str,
    detected_value: str,
    action: str | None,
    run_monitor_agent_session: MonitorAgentRunner,
) -> tuple[str | None, str | None]:
    action = _normalize_action(action) if action else None
    if action is None or action == "log":
        return None, action or "log"
    onboarding = worker.onboarding
    if onboarding is None:
        return None, "log"
    if action in {"notify", "page", "escalate"}:
        targets = await _resolve_action_targets(db, worker)
        for target in targets:
            await create_notification(
                db,
                user_id=target.id,
                notification_type="worker.monitor.alert",
                title=f"Worker monitor alert: {monitor.name}",
                body=f"{worker.name} reported {severity} on {monitor.monitor_type} ({detected_value}).",
                link="/chat",
            )
        try:
            await emit_outbound_webhook_event(
                db,
                event_type="worker.monitor.alert",
                project_id=worker.project_id,
                payload={
                    "worker_id": worker.id,
                    "worker_name": worker.name,
                    "monitor_id": monitor.id,
                    "monitor_name": monitor.name,
                    "monitor_type": monitor.monitor_type,
                    "severity": severity,
                    "detected_value": detected_value,
                    "action": action,
                },
            )
        except Exception:
            logger.exception("Failed to emit worker monitor webhook")
        await log_worker_escalation(
            db,
            worker=worker,
            reason=f"{severity} {monitor.monitor_type} alert",
            context_summary=f"Monitor '{monitor.name}' triggered action '{action}' with value {detected_value}.",
            escalation_channel=action,
        )
        return None, action
    if action in {"create_ticket", "diagnose", "auto_fix"}:
        if not can_worker_execute_action(worker, onboarding, action):
            targets = await _resolve_action_targets(db, worker)
            if targets:
                await create_notification(
                    db,
                    user_id=targets[0].id,
                    notification_type="worker.monitor.escalation_required",
                    title=f"Worker action requires escalation: {monitor.name}",
                    body=(
                        f"{worker.name} reached {severity} on {monitor.monitor_type}, "
                        f"but autonomy policy blocked '{action}'."
                    ),
                    link="/chat",
                )
            await record_worker_trust_event(
                db,
                worker=worker,
                event_type="correct_escalation",
                reason=f"Autonomy gate blocked '{action}' for monitor {monitor.id}.",
            )
            await log_worker_escalation(
                db,
                worker=worker,
                reason=f"autonomy gate blocked {action}",
                context_summary=(
                    f"Monitor '{monitor.name}' reached {severity} and required escalation instead of '{action}'."
                ),
                escalation_channel=None,
            )
            return None, "escalate"
        session_id = await _create_monitor_session(
            db,
            session_factory,
            worker=worker,
            monitor=monitor,
            severity=severity,
            detected_value=detected_value,
            action="diagnosis" if action == "create_ticket" else action,
            run_monitor_agent_session=run_monitor_agent_session,
        )
        return session_id, action
    return None, action
