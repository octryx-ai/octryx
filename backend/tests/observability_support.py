"""Shared helpers for the observability tests."""

from __future__ import annotations

import uuid

from sqlalchemy import select

from app.middleware.security.rate_limit import clear_rate_limit_buckets
from app.models import Project, Role, Session, User, UserRole
from app.services.auth.tokens import create_access_token, hash_password
from app.services.auth_rate_limit import clear_all_auth_rate_limits


async def user_with_role(db, role_name: str) -> User:
    suffix = uuid.uuid4().hex[:8]
    user = User(
        id=str(uuid.uuid4()),
        username=f"{role_name}-{suffix}",
        email=f"{role_name}-{suffix}@example.com",
        password_hash=hash_password("obs-Test-Pw-123"),
        display_name=f"{role_name} {suffix}",
        is_active=True,
    )
    db.add(user)
    await db.flush()
    role = (await db.execute(select(Role).where(Role.name == role_name))).scalar_one()
    db.add(UserRole(user_id=user.id, role_id=role.id))
    await db.commit()
    return user


async def admin_user(db) -> User:
    return (await db.execute(select(User).where(User.username == "admin"))).scalar_one()


async def call_as(client, method: str, path: str, user: User, **kwargs):
    clear_rate_limit_buckets()
    clear_all_auth_rate_limits()
    client.cookies.clear()
    headers = {"Authorization": f"Bearer {create_access_token(user.id)}", **kwargs.pop("headers", {})}
    return await client.request(method, path, headers=headers, **kwargs)


async def workspace(db, name: str | None = None) -> Project:
    project = Project(id=str(uuid.uuid4()), name=name or f"obs-ws-{uuid.uuid4().hex[:8]}", config={})
    db.add(project)
    await db.flush()
    return project


async def session_for(db, user: User, *, origin: str = "chat", project: Project | None = None) -> Session:
    session = Session(
        id=str(uuid.uuid4()), user_id=user.id, project_id=project.id if project else None, agent_type="chat",
        origin=origin, metadata_={},
    )
    db.add(session)
    await db.flush()
    return session


async def run_summary(db, trace_id: str):
    """The ``turn_trace_summaries`` row of a trace."""
    from app.models import TurnTraceSummary

    return (await db.execute(select(TurnTraceSummary).where(TurnTraceSummary.trace_id == trace_id))).scalar_one()


def add_trace(db, trace, fields: dict) -> None:
    """Add a hand-built ``TurnTrace`` with its summary row (``fields`` from ``run_summary_fields``)."""
    from app.services.observability.run_summary import summary_row
    from app.time_utils import utc_now

    trace.id = trace.id or str(uuid.uuid4())
    trace.created_at = trace.created_at or utc_now()
    db.add(trace)
    db.add(summary_row(trace, fields))
