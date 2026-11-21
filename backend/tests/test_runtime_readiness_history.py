"""Runtime-readiness-blocked turns stay out of every model-visible history channel."""

import asyncio
import json
import uuid
from datetime import timedelta
from pathlib import Path

import pytest
from sqlalchemy import select

import app.agent.providers as providers_module
from app.agent.core.context.run_context import prepare_agent_run
from app.agent.core.context.runtime_readiness_history import exclude_runtime_readiness_blocked_turns
from app.agent.core.runtime import summarizer as summarizer_module
from app.models import Message, Session, TurnTrace, User
from app.services.session.runtime_readiness_gate import (
    RUNTIME_READINESS_GATE_TRACE_PROVIDER,
    evaluate_runtime_readiness,
)
from app.time_utils import utc_now

STALE_PROMPT = "Reply with exactly SHOULD-NOT-RUN."
STALE_MARKER = "SHOULD-NOT-RUN"
GATE_EXPLANATION = evaluate_runtime_readiness(
    [],
    skipped_runtimes=[
        {
            "provider_name": "bedrock",
            "model": "anthropic.claude-sonnet-4-6",
            "selection_status": "skipped",
            "selection_decision": {"skipped_reasons": ["aws_credentials_not_configured"]},
        }
    ],
).user_message
GATE_MARKER = "requires configuration before it can run"
BLOCKED_TURN = [("user", STALE_PROMPT, None), ("assistant", GATE_EXPLANATION, RUNTIME_READINESS_GATE_TRACE_PROVIDER)]


async def _seed_history(db, turns: list[tuple[str, str, str | None]]) -> tuple[User, Session, list[Message]]:
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    session = Session(id=str(uuid.uuid4()), user_id=admin.id, agent_type="diagnosis", metadata_={})
    db.add(session)
    started_at = utc_now() - timedelta(hours=1)
    messages = [
        Message(
            id=str(uuid.uuid4()),
            session_id=session.id,
            role=role,
            content=content,
            created_at=started_at + timedelta(seconds=index),
        )
        for index, (role, content, _trace_provider) in enumerate(turns)
    ]
    db.add_all(messages)
    await db.flush()
    db.add_all(
        TurnTrace(id=str(uuid.uuid4()), session_id=session.id, message_id=message.id, provider=trace_provider)
        for message, (_role, _content, trace_provider) in zip(messages, turns)
        if trace_provider
    )
    await db.commit()
    return admin, session, messages


def _real_turns(count: int, topic: str) -> list[tuple[str, str, str | None]]:
    return [
        ("user", f"real turn {index} about {topic}", None)
        if index % 2 == 0
        else ("assistant", f"real turn {index} about {topic}", "bedrock")
        for index in range(count)
    ]


async def _prepare(db, admin: User, session: Session, user_message: str, tmp_path: Path):
    return await prepare_agent_run(
        db=db,
        session_id=session.id,
        user_message=user_message,
        user_id=admin.id,
        project_id=None,
        agent_type="diagnosis",
        runtime_target_id=None,
        thinking_level="light",
        agent_definition=None,
        parent_session_id=None,
        sub_agent_depth=0,
        workspace_root=str(tmp_path),
        resolve_model_context_cap=lambda *args, **kwargs: asyncio.sleep(0, result=None),
        resolve_control_plane_runtimes_func=lambda *args, **kwargs: asyncio.sleep(0, result=[]),
        filter_tool_definitions=lambda definitions, _allow: definitions,
        exclude_tool_definitions=lambda definitions, _blocked: definitions,
        trim_messages_to_budget=lambda messages, _budget: messages,
    )


def _model_input_text(prepared) -> str:
    return "\n".join(str(message.get("content") or "") for message in prepared.messages)


@pytest.mark.asyncio
async def test_blocked_turns_are_excluded_as_units_including_consecutive_ones(db):
    _admin, session, messages = await _seed_history(
        db,
        [
            ("user", "Summarize the runtime configuration status.", None),
            ("assistant", "The runtime configuration is complete for Bedrock.", "bedrock"),
            *BLOCKED_TURN,
            *BLOCKED_TURN,
            *BLOCKED_TURN,
            ("user", "Reply with exactly READY-AFTER-RESTORE.", None),
            ("assistant", "READY-AFTER-RESTORE", "bedrock"),
        ],
    )

    kept = await exclude_runtime_readiness_blocked_turns(db, session_id=session.id, messages=messages)

    assert kept == [messages[0], messages[1], messages[8], messages[9]]


@pytest.mark.asyncio
async def test_content_equal_replies_without_the_gate_trace_are_kept(db):
    # Identification is by the gate's persisted trace, never by content: next to a real blocked
    # turn, a model reply that echoes the gate text and the same text without a trace stay history.
    _admin, session, messages = await _seed_history(
        db,
        [
            *BLOCKED_TURN,
            ("user", "Repeat the runtime configuration notice.", None),
            ("assistant", GATE_EXPLANATION, "bedrock"),
            ("user", STALE_PROMPT, None),
            ("assistant", GATE_EXPLANATION, None),
        ],
    )

    kept = await exclude_runtime_readiness_blocked_turns(db, session_id=session.id, messages=messages)

    assert kept == messages[2:]


@pytest.mark.asyncio
async def test_gate_traces_are_trusted_only_within_their_session(db):
    _admin, session, messages = await _seed_history(
        db,
        [("user", STALE_PROMPT, None), ("assistant", GATE_EXPLANATION, None)],
    )
    _other_admin, other_session, _other_messages = await _seed_history(db, [])
    db.add(
        TurnTrace(
            id=str(uuid.uuid4()),
            session_id=other_session.id,
            message_id=messages[1].id,
            provider=RUNTIME_READINESS_GATE_TRACE_PROVIDER,
        )
    )
    await db.commit()

    kept = await exclude_runtime_readiness_blocked_turns(db, session_id=session.id, messages=messages)

    assert kept == messages


@pytest.mark.asyncio
async def test_blocked_retries_do_not_crowd_real_history_out_of_the_recent_window(db, tmp_path: Path):
    # The gate explanation tells the user to send the request again; blocked retries are excluded before the recent
    # window is filled, so they never leave it without real history.
    admin, session, messages = await _seed_history(
        db,
        [
            ("user", "What is the root cause of incident INC-4711?", None),
            ("assistant", "Incident INC-4711 root cause: an expired TLS certificate.", "bedrock"),
            *(BLOCKED_TURN * 4),
        ],
    )

    prepared = await _prepare(db, admin, session, "Which certificate caused incident INC-4711?", tmp_path)

    assert prepared.history_count == 2
    assert prepared.history == [messages[0], messages[1]]
    assert STALE_MARKER not in _model_input_text(prepared)
    assert GATE_MARKER not in _model_input_text(prepared)


@pytest.mark.asyncio
async def test_blocked_turn_is_absent_from_context_compaction_in_a_long_session(db, tmp_path: Path):
    # The thread started blocked, then continued for 20 real messages, so the blocked turn
    # ages into the compaction source that is rendered into the protected system prompt.
    admin, session, messages = await _seed_history(db, [*BLOCKED_TURN, *_real_turns(20, "incident INC-4711")])

    prepared = await _prepare(db, admin, session, "Continue the INC-4711 investigation.", tmp_path)

    assert "Active context compaction" in prepared.system_prompt
    assert prepared.session_metadata["runtime_context_compaction"]["source_first_message_id"] == messages[2].id
    assert prepared.history_count == 20
    model_input = _model_input_text(prepared)
    assert STALE_MARKER not in model_input
    assert GATE_MARKER not in model_input


@pytest.mark.asyncio
async def test_execution_gate_turn_stays_in_prompt_history(db, tmp_path: Path):
    # Scope guard: only runtime-readiness turns are excluded; execution-gate turns keep their behavior.
    admin, session, messages = await _seed_history(
        db,
        [
            ("user", "Deploy the INC-4711 certificate fix to staging.", None),
            (
                "assistant",
                "Deploying the INC-4711 certificate fix to staging needs clarification before it can run.",
                "execution-gate",
            ),
        ],
    )

    prepared = await _prepare(db, admin, session, "Deploy the INC-4711 certificate fix to staging now.", tmp_path)

    assert prepared.history_count == 2
    assert messages[0] in prepared.history


@pytest.mark.asyncio
async def test_rolling_summary_input_excludes_blocked_turns(db, monkeypatch):
    # The rolling summary reads every persisted message and is replayed as a user message.
    _admin, session, _messages = await _seed_history(db, [*BLOCKED_TURN, *_real_turns(12, "incident INC-4711")])
    captured: list[str] = []

    class _RecordingProvider:
        async def chat(self, *, messages, **_kwargs):
            captured.append("\n".join(str(message.get("content") or "") for message in messages))
            return {
                "content": json.dumps(
                    {"goal": "g", "findings": [], "actions_taken": [], "open_items": [], "state": "unknown"}
                )
            }

    monkeypatch.setattr(providers_module, "get_provider", lambda **_kwargs: _RecordingProvider())

    await summarizer_module._update_summary(session.id, db)

    assert len(captured) == 1
    assert "real turn 0 about incident INC-4711" in captured[0]
    assert STALE_MARKER not in captured[0]
    assert GATE_MARKER not in captured[0]
    await db.refresh(session)
    # The counter indexes model-visible messages: 12 real messages minus the recent window of 8.
    assert session.metadata_["summary_message_count"] == 4
