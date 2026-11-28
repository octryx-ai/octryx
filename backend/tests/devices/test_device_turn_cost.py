"""The platform prices every device turn from the turn's own usage; the device's ``cost_usd`` is information only
(Claude Code's ``total_cost_usd`` is a session running total, restored on every resume)."""

from __future__ import annotations

import uuid

import pytest

from app.models import LLMModel, LLMProvider
from app.services.devices.jobs_channel import DeviceJobHandlers
from app.services.devices.turn_cost import price_turn
from tests.devices.device_support import RecordingConnection, chat_session, device_with_grant, user_named
from tests.devices.test_device_jobs import _event, _turn


async def _priced_model(db, model_id: str, *, cache: bool = True) -> None:
    provider = LLMProvider(id=str(uuid.uuid4()), name=f"p-{uuid.uuid4().hex[:6]}", driver="bedrock_api",
                           is_active=True)
    db.add(provider)
    db.add(LLMModel(id=str(uuid.uuid4()), provider_id=provider.id, model_id=model_id, pricing_input=1.0,
                    pricing_output=5.0, pricing_cache_read=0.1 if cache else None,
                    pricing_cache_write=1.25 if cache else None))
    await db.flush()


def _usage(by_model):
    return {"input_tokens": 0, "output_tokens": 0, "source": "transcript", "by_model": by_model}


async def _accepted_job(db):
    user = await user_named(db, "device-owner")
    device, _ = await device_with_grant(db, user)
    session = await chat_session(db, user)
    handlers, connection = DeviceJobHandlers(), RecordingConnection(device.id)
    job = await _turn(db, user, device, session)
    await handlers.tick(db, connection)
    await _event(db, handlers, connection, job, 1, "job_accepted", turn_id=job.turn_id)
    return job, handlers, connection


@pytest.mark.asyncio
async def test_a_turn_is_priced_per_model_from_the_catalog_and_an_unknown_model_is_named(db):
    await _priced_model(db, "eu.anthropic.claude-haiku-5-5")
    job, handlers, connection = await _accepted_job(db)
    usage = _usage({"claude-haiku-5-5": {"input_tokens": 1_000_000, "output_tokens": 200_000,
                                         "cache_read_input_tokens": 1_000_000, "cache_creation_input_tokens": 0},
                    "claude-unknown-9": {"input_tokens": 5, "output_tokens": 5}})
    await _event(db, handlers, connection, job, 2, "turn_finished", turn_id=job.turn_id, status="success",
                 result_text="Done.", usage=usage)
    assert float(job.cost_usd) == pytest.approx(1.0 + 1.0 + 0.1)
    assert job.usage["cost_source"] == "platform_from_usage"
    assert job.usage["unpriced_models"] == ["claude-unknown-9"]


@pytest.mark.asyncio
async def test_claude_codes_running_total_is_never_added_up(db):
    await _priced_model(db, "claude-sonnet-5-5")
    job, handlers, connection = await _accepted_job(db)
    seq = 2
    for running_total in (11.16, 15.81, 30.42):
        turn = {"claude-sonnet-5-5": {"input_tokens": 0, "output_tokens": 100_000,
                                      "cache_read_input_tokens": 1_000_000, "cache_creation_input_tokens": 0}}
        await _event(db, handlers, connection, job, seq, "turn_finished", turn_id=job.turn_id, status="success",
                     result_text="Done.", cost_usd=running_total, usage=_usage(turn))
        job.status, job.turn_state = "running", "running"
        seq += 1
    assert float(job.cost_usd) == pytest.approx(3 * (0.5 + 0.1))  # 3 turns x (output + cache reads), not 57.39
    assert job.usage["reported_cost_usd"] == 30.42


@pytest.mark.asyncio
async def test_a_one_hour_cache_write_costs_twice_the_input_at_the_list_price(db):
    result_usage = {"input_tokens": 0, "output_tokens": 0, "cache_read_input_tokens": 0,
                    "cache_creation_input_tokens": 2_000_000,
                    "cache_creation": {"ephemeral_1h_input_tokens": 1_000_000, "ephemeral_5m_input_tokens": 1_000_000}}
    priced = await price_turn(db, {"cost_usd": 187.19, "usage": result_usage}, model="claude-sonnet-5-5")
    assert priced["cost_usd"] == pytest.approx(4.0 + 2.5)
    assert priced["usage"]["reported_cost_usd"] == 187.19


@pytest.mark.asyncio
async def test_nothing_priceable_adds_no_cost(db):
    assert (await price_turn(db, {"cost_usd": 3.0}, model="claude-sonnet-5-5"))["cost_usd"] is None
    unknown = await price_turn(db, {"usage": {"input_tokens": 10}}, model="claude-unknown-9")
    assert unknown["cost_usd"] is None and unknown["usage"]["unpriced_models"] == ["claude-unknown-9"]
    nameless = await price_turn(db, {"usage": {"input_tokens": 10}}, model="")
    assert nameless["cost_usd"] is None
    job, handlers, connection = await _accepted_job(db)
    await _event(db, handlers, connection, job, 2, "turn_finished", turn_id=job.turn_id, status="success",
                 result_text="Done.", cost_usd=187.19)
    assert job.cost_usd is None
