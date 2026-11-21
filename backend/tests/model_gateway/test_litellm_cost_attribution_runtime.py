"""One runtime dispatch is exactly one usage event and charge, and persisted gateway traces carry no upstream response field."""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app.agent.loops.runtime._loop_runtime_turn import execute_runtime_turn
from app.agent.loops.runtime._loop_runtime_turn_inputs import RuntimeTurnInputs
from app.models import LLMModel, TurnTrace, TurnTraceSummary, UsageEvent
from tests.model_gateway.conftest import (
    ALIAS,
    CATALOG_INPUT_PRICE,
    CATALOG_OUTPUT_PRICE,
    CATALOG_TURN_COST,
    MESSAGES,
    FakeLiteLLMGateway,
    chat_body,
    gateway_runtime,
    stale_priced_gateway_model,
)
from tests.model_gateway.litellm_cost_attribution_support import _runtime_turn_kwargs, _session_for, _usage_events

#: These tests call provider drivers directly: they run as the platform (``tests/model_call_scope_plugin.py``).
pytestmark = pytest.mark.usefixtures("platform_model_call")


async def _persisted_traces(db, session_id: str) -> tuple[TurnTrace, TurnTraceSummary]:
    """The turn's persisted trace records, read back out of the database.

    Redaction is only proven by what was *stored*, so the assertions below query
    the ``turn_traces`` row the real writer inserted plus its run summary
    (``turn_trace_summaries``) — the places a turn's payload
    actually comes to rest.
    """

    trace = (await db.execute(select(TurnTrace).where(TurnTrace.session_id == session_id))).scalar_one()
    summary = (
        await db.execute(select(TurnTraceSummary).where(TurnTraceSummary.trace_id == trace.id))
    ).scalar_one()
    return trace, summary


LEAKS = ("sk-should-never-travel", "call-should-not-travel", "fp-should-not-travel")


def _noisy_gateway() -> FakeLiteLLMGateway:
    """A gateway whose response carries fields that must not survive the adapter."""

    return FakeLiteLLMGateway(
        chat_payload=chat_body(
            usage={
                "prompt_tokens": 1000,
                "completion_tokens": 500,
                "litellm_call_id": "call-should-not-travel",
                "upstream_api_key": "sk-should-never-travel",
            },
            system_fingerprint="fp-should-not-travel",
        )
    )


async def test_one_runtime_dispatch_creates_exactly_one_usage_event_and_one_charge(
    db, build_gateway_client
) -> None:
    """One supported dispatch, one ``UsageEvent``, one charge — at the adapter's price.

    The model row carries the same synchronized catalog prices, so a second
    attribution from the database would double this turn. Both the row count and
    the session total are asserted, because either alone would miss one half of
    that.

    This is the whole duplicate-billing claim: within one dispatch there is no
    second, divergent charge. Replay of the same request across two dispatches is
    a different question, with no idempotency contract to hold it to — see
    ``test_a_second_dispatch_is_a_second_charge_because_no_retry_dedup_exists``.
    """

    provider = await stale_priced_gateway_model(db)
    admin_user, session = await _session_for(db)
    client = build_gateway_client(_noisy_gateway())
    response = await client.chat(MESSAGES, model=ALIAS)

    result = await execute_runtime_turn(RuntimeTurnInputs(
        **_runtime_turn_kwargs(
            db,
            session_id=session.id,
            user_id=admin_user.id,
            runtime=gateway_runtime(provider_name=provider.name, model=ALIAS),
            response=response,
        )
    ))
    await db.commit()

    assert result["action"] == "ok"
    events = await _usage_events(db, session.id)
    session_total = (
        await db.execute(select(func.sum(UsageEvent.cost)).where(UsageEvent.session_id == session.id))
    ).scalar_one()
    assert len(events) == 1
    assert events[0].cost == CATALOG_TURN_COST
    assert Decimal(str(session_total)) == CATALOG_TURN_COST
    assert events[0].cost_source == "catalog_pricing"
    assert events[0].cost_status == "catalog_pricing"
    # The stale catalog price is still there: the single charge is the adapter's,
    # not a re-pricing that happened to agree.
    model = (await db.execute(select(LLMModel).where(LLMModel.model_id == ALIAS))).scalar_one()
    assert (model.pricing_input, model.pricing_output) == (CATALOG_INPUT_PRICE, CATALOG_OUTPUT_PRICE)


async def test_a_second_dispatch_is_a_second_charge_because_no_retry_dedup_exists(
    db, build_gateway_client
) -> None:
    """Recorded scope, not an aspiration: two dispatches bill twice.

    Neither the contract nor ``record_usage_event`` defines a stable idempotency
    key for a usage event, so cross-request retry deduplication does not exist and
    is deliberately **not** implemented here (it is an open follow-up). This test
    states the current contract so no reader mistakes
    "exactly one charge per dispatch" for "exactly one charge per request". A
    follow-up that adds retry dedup must replace it.
    """

    provider = await stale_priced_gateway_model(db)
    admin_user, session = await _session_for(db)
    client = build_gateway_client(_noisy_gateway())
    response = await client.chat(MESSAGES, model=ALIAS)

    for _ in range(2):
        await execute_runtime_turn(RuntimeTurnInputs(
            **_runtime_turn_kwargs(
                db,
                session_id=session.id,
                user_id=admin_user.id,
                runtime=gateway_runtime(provider_name=provider.name, model=ALIAS),
                response=response,
            )
        ))
    await db.commit()

    events = await _usage_events(db, session.id)
    assert len(events) == 2
    assert [event.cost for event in events] == [CATALOG_TURN_COST, CATALOG_TURN_COST]


async def test_the_persisted_trace_of_a_gateway_turn_carries_no_upstream_response_field(
    db, build_gateway_client
) -> None:
    """Redaction proven from stored rows, not from a stub's arguments.

    The turn runs with the real trace writer, then the ``turn_traces`` row and its
    run summary are queried back. Both payload columns are pinned to their closed field set,
    which is the positive form of the same statement: a field nobody admitted
    cannot be missing by accident, and a future writer that dumped the whole
    response into the trace would fail here rather than quietly widen it.
    """

    provider = await stale_priced_gateway_model(db)
    admin_user, session = await _session_for(db)
    client = build_gateway_client(_noisy_gateway())
    response = await client.chat(MESSAGES, model=ALIAS)

    await execute_runtime_turn(RuntimeTurnInputs(
        **_runtime_turn_kwargs(
            db,
            session_id=session.id,
            user_id=admin_user.id,
            runtime=gateway_runtime(provider_name=provider.name, model=ALIAS),
            response=response,
        )
    ))
    await db.commit()

    trace, summary = await _persisted_traces(db, session.id)
    assert set(trace.usage_json) == {"prompt_tokens", "completion_tokens", "cost", "cost_source", "gateway_evidence"}
    assert trace.usage_json["cost_source"] == "catalog_pricing"
    assert set(trace.raw_output) == {"content", "tool_calls", "runtime_attempts", "thinking"}
    assert summary.outcome == "completed"
    stored = str(
        [
            trace.usage_json,
            trace.raw_output,
            trace.input_messages_json,
            trace.context_snapshot_json,
            trace.tool_trace_json,
            [summary.run_key, summary.agent_label, summary.provider, summary.model],
        ]
    )
    for leak in LEAKS:
        assert leak not in stored
