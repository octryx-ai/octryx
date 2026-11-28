"""The coding engine and the route of a workflow run, for the run lists and the run card."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import DeviceJob, Session, WorkflowRunSession
from ..agent_gateway.engine_keys import ENGINE_CLAUDE_CODE, ENGINES, SESSION_ENGINE_KEY
from ..agent_gateway.seat_credential import PROFILE_GOVERNED, PROFILE_SEAT

ROUTE_OWN_SUBSCRIPTION = "own_subscription"
ROUTE_COMPANY_MODEL = "company_model"
GATEWAY_PROFILE_KEY = "gateway_profile"
_NONE: dict[str, str | None] = {"engine": None, "route": None}


def route_of(profile: object) -> str | None:
    value = str(profile or "")
    if value == PROFILE_SEAT or value.startswith("local:"):
        return ROUTE_OWN_SUBSCRIPTION
    if value == PROFILE_GOVERNED:
        return ROUTE_COMPANY_MODEL
    return None


def _engine(value: object) -> str:
    return value if value in ENGINES else ENGINE_CLAUDE_CODE  # type: ignore[return-value]


async def run_engine_routes(db: AsyncSession, run_ids: Iterable[str]) -> dict[str, dict[str, str | None]]:
    ids = sorted(set(run_ids))
    if not ids:
        return {}
    links = (await db.execute(
        select(WorkflowRunSession.run_id, WorkflowRunSession.session_id).where(WorkflowRunSession.run_id.in_(ids))
        .order_by(WorkflowRunSession.linked_at.desc())
    )).all()
    sessions_of: dict[str, list[str]] = {}
    for run_id, session_id in links:
        sessions_of.setdefault(str(run_id), []).append(str(session_id))
    session_ids = {session_id for items in sessions_of.values() for session_id in items}
    newest_job: dict[str, tuple[Any, str, str]] = {}
    gateway: dict[str, dict[str, str | None]] = {}
    if session_ids:
        for session_id, engine, profile, created_at in (await db.execute(
            select(DeviceJob.session_id, DeviceJob.engine, DeviceJob.profile, DeviceJob.created_at)
            .where(DeviceJob.session_id.in_(session_ids)).order_by(DeviceJob.created_at.desc())
        )).all():
            newest_job.setdefault(str(session_id), (created_at, str(engine or ""), str(profile or "")))
        for session_id, metadata in (await db.execute(
            select(Session.id, Session.metadata_).where(Session.id.in_(session_ids))
        )).all():
            data = metadata if isinstance(metadata, dict) else {}
            if data.get(GATEWAY_PROFILE_KEY):
                gateway[str(session_id)] = {"engine": _engine(data.get(SESSION_ENGINE_KEY)),
                                            "route": route_of(data.get(GATEWAY_PROFILE_KEY))}
    answer: dict[str, dict[str, str | None]] = {}
    for run_id in ids:
        linked = sessions_of.get(run_id, [])
        jobs = [newest_job[session_id] for session_id in linked if session_id in newest_job]
        if jobs:
            _created, engine, profile = max(jobs, key=lambda job: job[0])
            answer[run_id] = {"engine": _engine(engine), "route": route_of(profile)}
            continue
        answer[run_id] = next((dict(gateway[session_id]) for session_id in linked if session_id in gateway),
                              dict(_NONE))
    return answer


__all__ = ["ROUTE_COMPANY_MODEL", "ROUTE_OWN_SUBSCRIPTION", "route_of", "run_engine_routes"]
