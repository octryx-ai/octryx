"""Shared helpers for the test_product_run_chat_binding_* modules."""

from __future__ import annotations

import uuid

from sqlalchemy import select

from app.agent.core.runtime.runtime_errors import RUNTIME_ERROR_TRANSIENT, ProviderRuntimeError
from app.agent.engine import run_agent
from app.models import Project, User
from app.models import Session as ChatSession
from app.models.runtime.product_run import ProductRun, ProductRunAttempt, ProductRunTransition
from tests.product_run_chat_support import TOOL
from tests.run_capability_support import UNDECLARED_READ_ONLY_RUN

TOOL_CALL = {"id": "call_1", "type": "function", "function": {"name": TOOL, "arguments": "{}"}}


TOOL_RESPONSE = {"content": "", "tool_calls": [TOOL_CALL], "usage": {"prompt_tokens": 11, "completion_tokens": 3}}


FINAL_RESPONSE = {
    "content": "It is midnight UTC.",
    "tool_calls": None,
    "usage": {"prompt_tokens": 7, "completion_tokens": 2},
}


TRANSIENT = ProviderRuntimeError("upstream overloaded", error_class=RUNTIME_ERROR_TRANSIENT)


async def _admin(db) -> User:
    return (await db.execute(select(User).where(User.username == "admin"))).scalar_one()


async def _session(db, *, with_workspace: bool = True, project_id: str | None = None) -> ChatSession:
    admin = await _admin(db)
    if with_workspace and project_id is None:
        project = Project(name=f"run-binding-{uuid.uuid4().hex[:10]}", config={}, is_active=True)
        db.add(project)
        await db.flush()
        project_id = project.id
    session = ChatSession(
        id=str(uuid.uuid4()), user_id=admin.id, project_id=project_id, agent_type="chat", status="running", metadata_=dict(UNDECLARED_READ_ONLY_RUN)
    )
    db.add(session)
    await db.commit()
    return session


def _turn(db, session: ChatSession, *, run_origin: str | None = "chat_turn", **kwargs):
    return run_agent(
        session_id=session.id,
        user_message="What time is it?",
        user_id=session.user_id,
        project_id=session.project_id,
        agent_type="chat",
        db=db,
        run_origin=run_origin,
        **kwargs,
    )


async def _drain(events) -> list:
    return [event async for event in events]


async def _attempt(db, session_id: str) -> ProductRunAttempt:
    return (
        await db.execute(
            select(ProductRunAttempt)
            .join(ProductRun, ProductRun.id == ProductRunAttempt.run_id)
            .where(ProductRun.session_id == session_id)
        )
    ).scalar_one()


async def _audit(db, run_id: str) -> list[tuple[str | None, str, str | None]]:
    rows = await db.execute(
        select(ProductRunTransition.from_state, ProductRunTransition.to_state, ProductRunTransition.end_reason)
        .where(ProductRunTransition.run_id == run_id)
        .order_by(ProductRunTransition.sequence)
    )
    return [tuple(row) for row in rows]


OPENED = [(None, "requested", None), ("requested", "admitted", None), ("admitted", "running", None)]
