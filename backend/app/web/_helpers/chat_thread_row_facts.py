"""Row facts of the chat sidebar beyond the transcript: last activity and the device a thread runs on."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import DeviceJob, UserDevice
from ...models import Session as AgentSession
from ...services.agent_gateway.engine_keys import ENGINE_CLAUDE_CODE, ENGINES


def session_last_activity(session: AgentSession) -> datetime | None:
    return session.last_activity_at


def session_last_activity_column() -> Any:
    return AgentSession.last_activity_at


async def _newest_jobs(db: AsyncSession, session_ids: set[str]) -> dict[str, tuple[str, str]]:
    rows = (
        await db.execute(
            select(DeviceJob.session_id, DeviceJob.engine, DeviceJob.model)
            .where(DeviceJob.session_id.in_(session_ids))
            .order_by(DeviceJob.created_at.desc())
        )
    ).all()
    newest: dict[str, tuple[str, str]] = {}
    for session_id, engine, model in rows:
        newest.setdefault(str(session_id), (str(engine or ""), str(model or "")))
    return newest


async def load_device_targets(db: AsyncSession, sessions: list[AgentSession]) -> dict[str, dict[str, str | None]]:
    device_by_session: dict[str, str] = {}
    recorded: dict[str, dict[str, Any]] = {}
    for session in sessions:
        target = (session.metadata_ or {}).get("execution_target")
        if isinstance(target, dict) and target.get("kind") == "device" and target.get("device_id"):
            device_by_session[session.id] = str(target["device_id"])
            recorded[session.id] = target
    if not device_by_session:
        return {}
    rows = (
        await db.execute(
            select(UserDevice.id, UserDevice.name, UserDevice.owner_user_id).where(
                UserDevice.id.in_(set(device_by_session.values()))
            )
        )
    ).all()
    devices = {str(device_id): (str(name or ""), str(owner or "")) for device_id, name, owner in rows}
    owners = {session.id: session.user_id for session in sessions}
    jobs = await _newest_jobs(db, set(device_by_session))
    targets: dict[str, dict[str, str | None]] = {}
    for session_id, device_id in device_by_session.items():
        name, owner = devices.get(device_id, ("", ""))
        if name and owner == owners.get(session_id):
            engine, reported = jobs.get(session_id, ("", ""))
            target = recorded[session_id]
            targets[session_id] = {
                "kind": "device", "device_name": name,
                "engine": engine if engine in ENGINES else ENGINE_CLAUDE_CODE,
                "profile": str(target.get("profile") or "") or None,
                "model": reported or str(target.get("model") or "") or None,
            }
    return targets


__all__ = ["load_device_targets", "session_last_activity", "session_last_activity_column"]
