"""A run without a ready runtime stops with needs_configuration before any provider call, and the blocked turn is excluded once the runtime is restored."""

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

import app.agent.engine as engine_module
import app.agent.engine._engine_turn_admission as turn_admission_module
from app.agent.engine import run_agent
from app.models import Message, Session, ThreadContext, TurnTrace, User
from app.models.runtime.provider_oauth_config import ProviderOAuthConfig
from app.services.chat_turn_background import drain_chat_turn_background_tasks
from app.services.session.execution_gate import ExecutionGateDecision
from app.services.session.message_dispatch import send_session_message
from app.services.session.runtime_readiness_gate import RUNTIME_READINESS_GATE_TRACE_PROVIDER
from app.web._helpers.workspace import _load_chat_message_page
from tests.runtime_readiness_fail_closed_support import _bedrock_target, _clear_runtime_targets


@pytest.mark.asyncio
async def test_run_agent_stops_with_needs_configuration_before_any_provider_call(db, monkeypatch):
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    await _clear_runtime_targets(db)
    _provider, target = await _bedrock_target(db, credentials_configured=False)
    session = Session(
        id=str(uuid.uuid4()),
        user_id=admin.id,
        project_id=None,
        agent_type="diagnosis",
        status="running",
        metadata_={},
    )
    db.add(session)
    await db.commit()

    monkeypatch.setattr(
        turn_admission_module,
        "evaluate_execution_gate",
        lambda _profile: ExecutionGateDecision(
            allowed=True, status="allowed", decision_source="test", reason="test", user_message=""
        ),
    )
    provider_calls: list[object] = []

    async def _forbidden_chat(*args, **kwargs):
        provider_calls.append((args, kwargs))
        raise AssertionError("no provider call may happen without an executable runtime")

    def _forbidden_provider(**kwargs):
        provider_calls.append(kwargs)
        raise AssertionError("no provider may be initialized without an executable runtime")

    monkeypatch.setattr(engine_module, "_chat_with_runtime_fallback", _forbidden_chat)
    monkeypatch.setattr(engine_module, "get_provider", _forbidden_provider)

    events = [
        event
        async for event in run_agent(
            session_id=session.id,
            user_message="Explain the deployment status.",
            user_id=admin.id,
            project_id=None,
            agent_type="diagnosis",
            db=db,
            runtime_target_id=target.id,
        )
    ]

    assert provider_calls == []
    assert len(events) == 1
    assert "requires configuration" in events[0].content
    assert "aws_credentials_not_configured" in events[0].content

    message = (
        await db.execute(select(Message).where(Message.session_id == session.id, Message.role == "assistant"))
    ).scalar_one()
    assert message.content == events[0].content
    trace = (await db.execute(select(TurnTrace).where(TurnTrace.message_id == message.id))).scalar_one()
    assert trace.provider == "runtime-readiness-gate"
    assert trace.raw_output["source"] == "runtime_readiness"
    assert trace.raw_output["status"] == "needs_configuration"
    assert trace.raw_output["skipped_targets"][0]["target_id"] == target.id
    assert trace.raw_output["skipped_targets"][0]["skipped_reasons"] == ["aws_credentials_not_configured"]
    # The blocked turn did not advance the conversation: no thread context is derived from it.
    thread_context = await db.execute(select(ThreadContext).where(ThreadContext.session_id == session.id))
    assert thread_context.scalar_one_or_none() is None


@pytest.mark.asyncio
async def test_prompt_after_restored_runtime_excludes_blocked_turn_and_answers_latest_prompt(db, monkeypatch):
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    await _clear_runtime_targets(db)
    provider, target = await _bedrock_target(db, credentials_configured=False)
    session = Session(
        id=str(uuid.uuid4()),
        user_id=admin.id,
        project_id=None,
        agent_type="diagnosis",
        status="running",
        metadata_={},
    )
    db.add(session)
    await db.commit()
    monkeypatch.setattr(
        turn_admission_module,
        "evaluate_execution_gate",
        lambda _profile: ExecutionGateDecision(
            allowed=True, status="allowed", decision_source="test", reason="test", user_message=""
        ),
    )
    dispatched: list[list[dict]] = []
    dispatched_target_ids: list[str | None] = []

    async def _record_chat(*, runtimes, messages, tools, max_tokens=4096, reasoning_effort=None):
        dispatched.append([dict(message) for message in messages])
        dispatched_target_ids.append(runtimes[0].get("target_id"))
        return (
            {"content": "READY-AFTER-RESTORE", "tool_calls": None, "model": target.model_id, "usage": {}},
            runtimes[0],
        )

    monkeypatch.setattr(engine_module, "_chat_with_runtime_fallback", _record_chat)

    async def _send(prompt: str) -> list:
        # Mirrors the chat route: the turn's user message is persisted before run_agent.
        user_message = Message(id=str(uuid.uuid4()), session_id=session.id, role="user", content=prompt)
        db.add(user_message)
        session.metadata_ = {**(session.metadata_ or {}), "current_turn_user_message_id": user_message.id}
        await db.commit()
        return [
            event
            async for event in run_agent(
                session_id=session.id,
                user_message=prompt,
                user_id=admin.id,
                project_id=None,
                agent_type="diagnosis",
                db=db,
                runtime_target_id=target.id,
            )
        ]

    stale_prompt = "Reply with exactly SHOULD-NOT-RUN."
    blocked_events = await _send(stale_prompt)
    assert dispatched == []
    assert "requires configuration" in blocked_events[0].content

    db.add(ProviderOAuthConfig(provider_id=provider.id, aws_static_credentials_configured=True))
    await db.commit()
    await db.refresh(provider, attribute_names=["oauth_config"])
    latest_prompt = "Reply with exactly READY-AFTER-RESTORE."
    await _send(latest_prompt)

    assert dispatched, "the restored runtime must execute the new prompt"
    assert set(dispatched_target_ids) == {target.id}
    # The blocked turn never reached a model and is left out whole: neither the stale prompt
    # nor the platform-authored explanation (which a live model repeated) is model input.
    conversation = [message for message in dispatched[0] if message.get("role") != "system"]
    assert [(message["role"], message["content"]) for message in conversation] == [("user", latest_prompt)]
    dispatched_text = "\n".join(str(message.get("content") or "") for message in dispatched[0])
    assert stale_prompt not in dispatched_text
    assert blocked_events[0].content not in dispatched_text
    assert "Structured Thread Context" not in dispatched_text

    # Model input only: the chat transcript still shows the blocked turn with its gate trace.
    rows, _has_more = await _load_chat_message_page(
        db, session=session, user=admin, workspace_root=None, selected_runtime_label=""
    )
    assert [row["content"] for row in rows if row["role"] == "user"] == [stale_prompt, latest_prompt]
    gate_rows = [row for row in rows if row["content"] == blocked_events[0].content]
    assert len(gate_rows) == 1
    assert gate_rows[0]["providerName"] == RUNTIME_READINESS_GATE_TRACE_PROVIDER
    gate_trace = await db.get(TurnTrace, gate_rows[0]["turnTraceId"])
    assert gate_trace is not None
    assert gate_trace.raw_output["status"] == "needs_configuration"


@pytest.mark.asyncio
async def test_api_message_path_without_current_turn_id_excludes_blocked_turn(db, monkeypatch):
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    await _clear_runtime_targets(db)
    provider, target = await _bedrock_target(db, credentials_configured=False)
    session = Session(
        id=str(uuid.uuid4()),
        user_id=admin.id,
        project_id=None,
        agent_type="diagnosis",
        status="active",
        metadata_={},
    )
    db.add(session)
    await db.commit()
    monkeypatch.setattr(
        turn_admission_module,
        "evaluate_execution_gate",
        lambda _profile: ExecutionGateDecision(
            allowed=True, status="allowed", decision_source="test", reason="test", user_message=""
        ),
    )
    dispatched: list[list[dict]] = []

    async def _record_chat(*, runtimes, messages, tools, max_tokens=4096, reasoning_effort=None):
        dispatched.append([dict(message) for message in messages])
        return (
            {"content": "READY-AFTER-RESTORE-API", "tool_calls": None, "model": target.model_id, "usage": {}},
            runtimes[0],
        )

    monkeypatch.setattr(engine_module, "_chat_with_runtime_fallback", _record_chat)

    async def _send(prompt: str):
        # The /api/v1 message route: marks the turn and clears the marker when the turn ends.
        responses = await send_session_message(
            db,
            session_id=session.id,
            content=prompt,
            user_id=admin.id,
            project_id=None,
            agent_type="diagnosis",
            run_agent_func=run_agent,
            session_factory=async_sessionmaker(db.bind, class_=AsyncSession, expire_on_commit=False),
        )
        await drain_chat_turn_background_tasks(session.id)
        return responses

    stale_prompt = "Reply with exactly SHOULD-NOT-RUN-API."
    blocked_responses = await _send(stale_prompt)
    assert dispatched == []
    assert "requires configuration" in blocked_responses[-1].content
    await db.refresh(session)
    assert "current_turn_user_message_id" not in (session.metadata_ or {})

    db.add(ProviderOAuthConfig(provider_id=provider.id, aws_static_credentials_configured=True))
    await db.commit()
    await db.refresh(provider, attribute_names=["oauth_config"])
    latest_prompt = "Reply with exactly READY-AFTER-RESTORE-API."
    await _send(latest_prompt)

    assert dispatched, "the restored runtime must execute the new prompt"
    conversation = {(message["role"], message["content"]) for message in dispatched[0] if message["role"] != "system"}
    assert conversation == {("user", latest_prompt)}
    dispatched_text = "\n".join(str(message.get("content") or "") for message in dispatched[0])
    assert stale_prompt not in dispatched_text
    assert blocked_responses[-1].content not in dispatched_text
