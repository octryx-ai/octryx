"""Thread usage stats report cost, model breakdown and keep deterministic steps out of LLM request counts."""

import uuid
from decimal import Decimal

import pytest

from app.models import Message, Session, ToolCall, TurnTrace, UsageEvent
from app.web._helpers._serialization_ext import _serialize_thread_stats
from app.web._helpers.thread_usage_stats import _load_thread_usage_stats


@pytest.mark.asyncio
async def test_thread_usage_stats_include_cost_and_model_breakdown(db, auth_user):
    session = Session(
        id=str(uuid.uuid4()),
        user_id=auth_user.id,
        status="active",
        metadata_={"title": "Cost stats"},
    )
    db.add(session)
    db.add_all(
        [
            Message(
                id=str(uuid.uuid4()),
                session_id=session.id,
                role="user",
                content="Test cost stats",
            ),
            UsageEvent(
                id=str(uuid.uuid4()),
                session_id=session.id,
                user_id=auth_user.id,
                provider="bedrock",
                model="anthropic.claude-sonnet-4-6",
                tokens_in=1000,
                tokens_out=100,
                cost=Decimal("0.004500"),
            ),
            UsageEvent(
                id=str(uuid.uuid4()),
                session_id=session.id,
                user_id=auth_user.id,
                provider="bedrock",
                model="anthropic.claude-haiku-4-5",
                tokens_in=200,
                tokens_out=50,
                cost=Decimal("0.000700"),
            ),
            UsageEvent(
                id=str(uuid.uuid4()),
                session_id=session.id,
                user_id=auth_user.id,
                provider="bedrock",
                model="anthropic.claude-sonnet-4-6",
                tokens_in=500,
                tokens_out=25,
                cost=Decimal("0.002000"),
            ),
            TurnTrace(
                id=str(uuid.uuid4()),
                session_id=session.id,
                provider="bedrock",
                model="anthropic.claude-sonnet-4-6",
                usage_json={
                    "bedrock_input_tokens_non_cached": 1400,
                    "bedrock_cache_read_input_tokens": 250,
                    "bedrock_cache_write_input_tokens": 50,
                },
            ),
        ]
    )
    await db.flush()

    stats = await _load_thread_usage_stats(db, session_ids=[session.id])
    payload = _serialize_thread_stats(stats)

    assert payload is not None
    assert payload["totalCost"] == 0.0072
    assert payload["requestCount"] == 3
    assert payload["inputTokens"] == 1700
    assert payload["outputTokens"] == 175
    assert payload["nonCachedInputTokens"] == 1400
    assert payload["cacheReadInputTokens"] == 250
    assert payload["cacheWriteInputTokens"] == 50
    assert payload["costByModel"][0] == {
        "provider": "bedrock",
        "model": "anthropic.claude-sonnet-4-6",
        "requestCount": 2,
        "inputTokens": 1500,
        "outputTokens": 125,
        "cost": 0.0065,
    }
    assert payload["costByModel"][1]["model"] == "anthropic.claude-haiku-4-5"
    assert payload["costByModel"][1]["cost"] == 0.0007


@pytest.mark.asyncio
async def test_thread_usage_stats_keep_deterministic_steps_out_of_llm_requests(db, auth_user):
    session = Session(
        id=str(uuid.uuid4()),
        user_id=auth_user.id,
        status="active",
        metadata_={"title": "Workflow stats"},
    )
    assistant_message = Message(
        id=str(uuid.uuid4()),
        session_id=session.id,
        role="assistant",
        content="Topology workflow evidence collected.",
        model="deterministic_workflow",
        tokens_in=400,
        tokens_out=20,
    )
    db.add_all(
        [
            session,
            Message(id=str(uuid.uuid4()), session_id=session.id, role="user", content="Draw topology"),
            assistant_message,
            ToolCall(
                id=str(uuid.uuid4()),
                session_id=session.id,
                message_id=assistant_message.id,
                tool_name="aws_topology_snapshot",
                status="success",
            ),
            TurnTrace(
                id=str(uuid.uuid4()),
                session_id=session.id,
                message_id=assistant_message.id,
                context_snapshot_json={
                    "request_analysis": {"workflow_contract": {"workflow_id": "generic_diagram"}}
                },
                usage_json={},
            ),
        ]
    )
    await db.flush()

    stats = await _load_thread_usage_stats(db, session_ids=[session.id])
    payload = _serialize_thread_stats(stats)

    assert payload is not None
    assert payload["requestCount"] == 0
    assert payload["llmRequestCount"] == 0
    assert payload["toolCallCount"] == 1
    assert payload["turnTraceCount"] == 1
    assert payload["deterministicStepCount"] == 1
    assert "No LLM usage events" in payload["zeroCostReason"]
