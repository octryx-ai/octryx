"""A full direct-chat turn makes exactly one governed model call, attempted, usage-accounted and traced on the same target."""

from __future__ import annotations

import json

import pytest
from sqlalchemy import select

from app.agent.engine import run_agent
from app.models import ControlPlaneRuntimeTarget, TurnTrace, UsageEvent
from tests.observability_support import run_summary
from tests.pre_turn_model_call_boundary_support import (  # noqa: F401
    FAKE_AWS_KEY,
    FAKE_EMAIL,
    SECRET_PROMPT,
    _admin,
    _first_active_target,
    provider_recorder,
    runtime_resolutions,
)
from tests.turn_preparation_support import prepare_chat_turn

pytestmark = pytest.mark.workflow_proposals


@pytest.mark.asyncio
@pytest.mark.parametrize("explicit_target", [False, True])
async def test_direct_chat_turn_makes_exactly_one_governed_model_call(
    client, auth_headers, db, provider_recorder, runtime_resolutions, explicit_target  # noqa: F811
):
    admin = await _admin(db)
    target = await _first_active_target(db)
    prepare_kwargs: dict = {"db": db, "user": admin, "prompt": SECRET_PROMPT, "agent_type": "diagnosis"}
    if explicit_target:
        prepare_kwargs.update(runtime_target_id=target.id, runtime_target_id_explicit=True)
    session, runtime_target_id, thinking_level, agent_payload = await prepare_chat_turn(**prepare_kwargs)
    # Preparation made only the governed workflow proposal call, no turn call.
    assert provider_recorder.turn_calls() == []
    assert len(provider_recorder.proposal_calls()) == 1

    events = [
        event
        async for event in run_agent(
            session_id=session.id,
            user_message=SECRET_PROMPT,
            user_id=admin.id,
            project_id=session.project_id,
            agent_type=session.agent_type,
            db=db,
            runtime_target_id=runtime_target_id or None,
            thinking_level=thinking_level,
            agent_definition=agent_payload,
        )
    ]
    await db.commit()

    assert any(getattr(event, "content", None) == "PONG-775" for event in events)
    # Exactly one turn model call, attempted, usage-accounted and traced exactly once.
    assert len(provider_recorder.turn_calls()) == 1
    all_usage_rows = (await db.execute(select(UsageEvent).where(UsageEvent.session_id == session.id))).scalars().all()
    # The pre-turn proposal call is accounted once as its own event (dispatch owner on request_id).
    proposal_rows = [row for row in all_usage_rows if str(row.request_id or "").startswith("workflow_proposal:")]
    usage_rows = [row for row in all_usage_rows if row not in proposal_rows]
    assert len(proposal_rows) == 1
    turn_traces = (await db.execute(select(TurnTrace).where(TurnTrace.session_id == session.id))).scalars().all()
    assert (len(usage_rows), len(turn_traces)) == (1, 1)
    attempts = turn_traces[0].raw_output["runtime_attempts"]
    assert len(attempts) == 1
    selected = attempts[-1]
    # One target, one provider, one model across the call, the attempt, the usage event and the trace.
    active_target_ids = {
        row.id
        for row in (
            await db.execute(select(ControlPlaneRuntimeTarget).where(ControlPlaneRuntimeTarget.is_active.is_(True)))
        ).scalars()
    }
    assert selected["target_id"] in active_target_ids
    if explicit_target:
        assert selected["target_id"] == target.id
    assert selected["provider"] == usage_rows[0].provider == turn_traces[0].provider
    assert (
        selected["model"]
        == usage_rows[0].model
        == turn_traces[0].model
        == provider_recorder.turn_calls()[0]["model"]
    )
    # Guardrails ran before every provider call: no raw secret reached any provider.
    for call in provider_recorder.chat_calls:
        sent = provider_recorder.sent_text(call)
        assert FAKE_EMAIL not in sent
        assert FAKE_AWS_KEY not in sent

    # In the Observability run drawer: profile, policy, provider and model
    # are visible together, redacted.
    response = await client.get(
        "/api/v1/observability/runs/detail", params={"run_key": (await run_summary(db, turn_traces[0].id)).run_key}, headers=auth_headers
    )
    assert response.status_code == 200
    detail = response.json()
    profile = detail["effective_setup"]
    assert profile["status"] == "allowed"
    assert profile["profile_id"] == "direct_chat_safe"
    assert profile["decision_source"] == "direct_chat_safe"
    # No workflow is selected, and the trace says why with a closed reason code (roadmap item 5).
    assert profile["policy"] == {
        "source": "workflow_selection",
        "status": "unmatched",
        "selection_state": "none",
        "selection_reason_code": "proposal_none",
    }
    assert "llm_router" not in profile
    assert (detail["steps"][0]["provider"], detail["steps"][0]["model"]) == (selected["provider"], selected["model"])
    if explicit_target:
        assert profile["runtime"]["runtime_target_id"] == target.id
    # The projection carries routing metadata only, never prompt text.
    serialized_profile = json.dumps(profile)
    assert FAKE_EMAIL not in serialized_profile
    assert FAKE_AWS_KEY not in serialized_profile
    assert "PONG-775" not in serialized_profile
    # Reading the trace made no further provider call.
    assert len(provider_recorder.chat_calls) == 2
