"""Sessions, snapshots, traces and the fake runtime shared by the turn execution summary tests."""

import uuid

from sqlalchemy import select

import app.agent.engine as engine_module
from app.agent.engine import run_agent
from app.models import Message, Session, TurnTrace, User
from app.services.session.execution_gate import evaluate_execution_gate
from app.services.session.turn_execution_snapshot import (
    RUNTIME_OUTCOME_FINISHED,
    RUNTIME_OUTCOME_KEY,
    TURN_EXECUTION_SNAPSHOT_KEY,
    build_turn_execution_snapshot,
)
from app.services.session.turn_execution_summary_service import load_user_turn_execution_summary
from tests.run_capability_support import UNDECLARED_READ_ONLY_RUN

SECRET = "sk-live-SECRET-token-123"


async def _admin(db) -> User:
    return (await db.execute(select(User).where(User.username == "admin"))).scalar_one()


async def _session(db, user_id: str, metadata: dict | None = None) -> Session:
    session = Session(
        id=str(uuid.uuid4()),
        user_id=user_id,
        project_id=None,
        agent_type="diagnosis",
        status="running",
        metadata_={**UNDECLARED_READ_ONLY_RUN, **(metadata or {})},
    )
    db.add(session)
    await db.flush()
    return session


def _allowed_snapshot(
    *, user_message_id: str | None = None, sequence: int | None = None, finished: bool = False
) -> dict:
    profile = {
        "version": "execution_profile.v1",
        "status": "allowed",
        "profile_id": "direct_chat_safe",
        "decision_source": "direct_chat_safe",
        "execution_strategy": "direct",
    }
    snapshot = build_turn_execution_snapshot(
        execution_profile=profile,
        gate=evaluate_execution_gate(profile),
        session_metadata={"current_turn_user_message_id": user_message_id} if user_message_id else {},
        agent_definition=None,
    )
    snapshot["turn"]["sequence"] = sequence
    if finished:
        snapshot[RUNTIME_OUTCOME_KEY] = RUNTIME_OUTCOME_FINISHED
    return snapshot


async def _trace(
    db, session: Session, *, snapshot: dict | None, raw_output: dict | None = None, usage: dict | None = None
) -> TurnTrace:
    message = Message(id=str(uuid.uuid4()), session_id=session.id, role="assistant", content="Done.")
    db.add(message)
    await db.flush()
    context = {"system_prompt": f"prompt {SECRET}"}
    if snapshot is not None:
        context[TURN_EXECUTION_SNAPSHOT_KEY] = snapshot
    trace = TurnTrace(
        id=str(uuid.uuid4()),
        session_id=session.id,
        message_id=message.id,
        provider="openrouter",
        model="stepfun/step-3.5-flash:free",
        input_messages_json=[{"role": "user", "content": SECRET}],
        context_snapshot_json=context,
        tool_trace_json=[],
        raw_output=raw_output or {"content": "Done."},
        usage_json=usage if usage is not None else {"prompt_tokens": 3, "completion_tokens": 4},
    )
    db.add(trace)
    await db.flush()
    return trace


def _fake_runtime(monkeypatch, content: str = "Pong") -> None:
    async def fake_resolve_control_plane_runtimes(_db, runtime_target_id=None):
        return [{"provider_name": "copilot", "model": "claude-haiku-4.5"}]

    async def fake_chat_with_runtime_fallback(*, runtimes, messages, tools, max_tokens=4096, reasoning_effort=None):
        return (
            {
                "content": content,
                "tool_calls": None,
                "model": "claude-haiku-4.5",
                "usage": {"prompt_tokens": 7, "completion_tokens": 2, "total_tokens": 9},
            },
            runtimes[0],
        )

    monkeypatch.setattr(engine_module, "resolve_control_plane_runtimes", fake_resolve_control_plane_runtimes)
    monkeypatch.setattr(engine_module, "_chat_with_runtime_fallback", fake_chat_with_runtime_fallback)


async def _run_turn(db, session: Session, user_id: str, text: str = "ping") -> list:
    return [
        event
        async for event in run_agent(
            session_id=session.id,
            user_message=text,
            user_id=user_id,
            project_id=None,
            agent_type="diagnosis",
            db=db,
        )
    ]


async def _session_traces(db, session_id: str) -> list[TurnTrace]:
    return list(
        (
            await db.execute(
                select(TurnTrace).where(TurnTrace.session_id == session_id).order_by(TurnTrace.created_at.asc())
            )
        ).scalars()
    )


async def _user_message(db, session: Session, text: str = "deploy it") -> Message:
    message = Message(id=str(uuid.uuid4()), session_id=session.id, role="user", content=text)
    db.add(message)
    await db.flush()
    return message


async def _summary(db, user_id: str, trace: TurnTrace) -> dict:
    return await load_user_turn_execution_summary(db, user_id=user_id, trace_id=trace.id)
