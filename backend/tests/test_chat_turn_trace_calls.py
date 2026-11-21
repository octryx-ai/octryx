"""An answer's trace lists the turn's model calls, for seat and device turns too: each route links its answer
to a trace."""

from __future__ import annotations

import uuid
from datetime import timedelta

import pytest
from sqlalchemy import select

from app.models import DeviceJob, Message, OAuthGrant, TurnTrace, UserDevice
from app.models import Session as AgentSession
from app.services.agent_gateway.contract import GATEWAY_AUDIENCE, SCOPE_MODEL_INVOKE
from app.services.devices.run_trace import (
    GATEWAY_JOB_KEY,
    GATEWAY_TURN_KEY,
    device_answer_key,
    record_device_turn,
    stamp_gateway_session,
)
from app.services.model_gateway.inbound.anthropic_stream import Observation
from app.services.model_gateway.inbound.seat_transcript import SeatCallRecord
from app.services.model_gateway.inbound.seat_transcript import _write as write_seat_call
from app.services.oauth_provider import mint_access_token
from app.time_utils import utc_now
from tests.knowledge_evidence_seed_support import seed_member, seed_workspace
from tests.observability_support import admin_user


def _call(session_id: str, user_id: str, prompt: str, *, stop: str, text: str = "", tokens: int = 100) -> SeatCallRecord:
    observation = Observation(
        usage={"input_tokens": tokens, "output_tokens": 7, "cache_read_input_tokens": 3}, stop_reason=stop, text=text
    )
    return SeatCallRecord(
        session_id=session_id, user_id=user_id, model="claude-sonnet-5-5",
        body={"tools": [{"name": "Bash"}], "messages": [{"role": "user", "content": prompt}]},
        observation=observation, upstream_request_id="req", duration_ms=1500, status_code=200,
    )


async def _thread(db, user_id: str, **metadata) -> AgentSession:
    session = AgentSession(id=str(uuid.uuid4()), user_id=user_id, agent_type="chat", origin="model_gateway",
                           metadata_=metadata)
    db.add(session)
    await db.flush()
    return session


async def _answers(db, session_id: str) -> list[Message]:
    return list((await db.execute(select(Message).where(
        Message.session_id == session_id, Message.role == "assistant").order_by(Message.created_at))).scalars())


async def _trace_of(db, message_id: str) -> TurnTrace:
    return (await db.execute(select(TurnTrace).where(TurnTrace.message_id == message_id))).scalar_one()


@pytest.mark.asyncio
async def test_a_seat_answer_has_its_trace_and_the_route_lists_all_calls_of_its_turn(client, auth_headers, db):
    admin = await admin_user(db)
    thread = await _thread(db, admin.id)
    for prompt, stop, text, tokens in [("list the files", "tool_use", "", 100), ("list the files", "tool_use", "", 200),
                                       ("list the files", "end_turn", "Three files.", 300),
                                       ("and the tests?", "tool_use", "", 400),
                                       ("and the tests?", "end_turn", "Two tests.", 500)]:
        await write_seat_call(db, _call(thread.id, admin.id, prompt, stop=stop, text=text, tokens=tokens))
        await db.commit()

    first, second = await _answers(db, thread.id)
    first_trace, second_trace = await _trace_of(db, first.id), await _trace_of(db, second.id)
    response = await client.get(f"/chat/api/turn-traces/{first_trace.id}", headers=auth_headers)
    later = (await client.get(f"/chat/api/turn-traces/{second_trace.id}", headers=auth_headers)).json()

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == first_trace.id and body["promptOnDevice"] is False
    assert [call["tokens"]["input"] for call in body["calls"]] == [100, 200, 300]
    assert body["calls"][-1]["id"] == first_trace.id
    assert body["calls"][0] | {"id": "", "createdAt": ""} == {
        "id": "", "createdAt": "", "provider": "anthropic_seat", "model": "claude-sonnet-5-5", "durationMs": 1500,
        "stopReason": "tool_use", "tokens": {"input": 100, "output": 7, "cacheRead": 3, "cacheCreation": 0}}
    assert [call["tokens"]["input"] for call in later["calls"]] == [400, 500]
    # The message page names the trace, so the chat shows the trace button.
    page = (await client.get(f"/chat/api/sessions/{thread.id}/messages", headers=auth_headers)).json()
    by_id = {row["id"]: row for row in page["messages"]}
    assert by_id[first.id]["turnTraceId"] == first_trace.id
    assert by_id[second.id]["turnTraceId"] == second_trace.id


@pytest.mark.asyncio
async def test_a_call_trace_lists_no_calls_of_its_own(client, auth_headers, db):
    admin = await admin_user(db)
    thread = await _thread(db, admin.id)
    await write_seat_call(db, _call(thread.id, admin.id, "hi", stop="tool_use"))
    await db.commit()
    call = (await db.execute(select(TurnTrace).where(TurnTrace.session_id == thread.id))).scalar_one()

    body = (await client.get(f"/chat/api/turn-traces/{call.id}", headers=auth_headers)).json()

    assert call.message_id is None
    assert body["calls"] == [] and body["promptOnDevice"] is False


async def _device_job(db, owner_id: str, chat: AgentSession, claude_session: str | None) -> DeviceJob:
    device = UserDevice(id=f"dev-{uuid.uuid4().hex[:12]}", owner_user_id=owner_id, name="Mac", name_key="mac",
                        os="macos", public_key="pk")
    db.add(device)
    await db.flush()
    job = DeviceJob(id=str(uuid.uuid4()), device_id=device.id, owner_user_id=owner_id, session_id=chat.id,
                    folder="/src", profile="seat", model="claude-sonnet-5-5", turn_id="turn-1", turn_count=1,
                    claude_session_id=claude_session)
    db.add(job)
    db.add(Message(session_id=chat.id, role="user", content="run the tests",
                   created_at=utc_now() - timedelta(seconds=30)))
    await db.flush()
    return job


@pytest.mark.asyncio
async def test_a_device_answer_is_linked_and_says_its_prompt_stayed_on_the_device(client, auth_headers, db):
    admin = await admin_user(db)
    chat = await _thread(db, admin.id)
    job = await _device_job(db, admin.id, chat, claude_session=None)
    answer = Message(session_id=chat.id, role="assistant", content="All green.", idempotency_key=device_answer_key(job))
    db.add(answer)
    await record_device_turn(db, job, "turn_finished", {"status": "success", "usage": {"input_tokens": 9}})
    await db.commit()

    trace = await _trace_of(db, answer.id)
    body = (await client.get(f"/chat/api/turn-traces/{trace.id}", headers=auth_headers)).json()

    assert trace.provider == "device" and trace.input_messages_json == []
    assert body["calls"] == [] and body["promptOnDevice"] is True


@pytest.mark.asyncio
async def test_a_device_turn_lists_the_calls_it_sent_through_the_gateway(client, auth_headers, db):
    admin = await admin_user(db)
    chat = await _thread(db, admin.id)
    job = await _device_job(db, admin.id, chat, claude_session="claude-abc")
    gateway = await _thread(db, admin.id, gateway_session_key="claude-abc")
    await stamp_gateway_session(db, gateway, job.id, admin.id)  # the launcher registered the turn with its job
    for tokens in (11, 22):
        await write_seat_call(db, _call(gateway.id, admin.id, "run the tests", stop="tool_use", tokens=tokens))
    answer = Message(session_id=chat.id, role="assistant", content="All green.", idempotency_key=device_answer_key(job))
    db.add(answer)
    await record_device_turn(db, job, "turn_finished", {"status": "success"})
    await db.commit()

    trace = await _trace_of(db, answer.id)
    body = (await client.get(f"/chat/api/turn-traces/{trace.id}", headers=auth_headers)).json()

    assert [call["tokens"]["input"] for call in body["calls"]] == [11, 22]
    assert body["promptOnDevice"] is False


@pytest.mark.asyncio
async def test_a_device_turn_that_failed_without_an_answer_stays_unlinked(db):
    admin = await admin_user(db)
    chat = await _thread(db, admin.id)
    job = await _device_job(db, admin.id, chat, claude_session=None)
    await record_device_turn(db, job, "job_failed", {"reason": "crashed"})
    await db.commit()

    trace = (await db.execute(select(TurnTrace).where(TurnTrace.session_id == chat.id))).scalar_one()
    assert trace.message_id is None


@pytest.mark.asyncio
async def test_a_resumed_device_turn_lists_the_calls_of_its_own_launcher_key(client, auth_headers, db):
    # Turn 2 of a device job resumes Claude session "claude-abc" but sends its calls under a new launcher key;
    # matching by the Claude session alone would show none of them and only turn 1's.
    admin = await admin_user(db)
    chat = await _thread(db, admin.id)
    job = await _device_job(db, admin.id, chat, claude_session="claude-abc")
    first = await _thread(db, admin.id, gateway_session_key="claude-abc")
    for tokens in (11, 22):
        await write_seat_call(db, _call(first.id, admin.id, "run the tests", stop="tool_use", tokens=tokens))
    job.turn_id = "turn-2"
    db.add(Message(session_id=chat.id, role="user", content="now fix them", created_at=utc_now() - timedelta(seconds=5)))
    second = await _thread(db, admin.id, gateway_session_key="launcher-key-2")
    await stamp_gateway_session(db, second, job.id, admin.id)
    for tokens in (33, 44):
        await write_seat_call(db, _call(second.id, admin.id, "now fix them", stop="tool_use", tokens=tokens))
    answer = Message(session_id=chat.id, role="assistant", content="Fixed.", idempotency_key=device_answer_key(job))
    db.add(answer)
    await record_device_turn(db, job, "turn_finished", {"status": "success"})
    await db.commit()

    trace = await _trace_of(db, answer.id)
    body = (await client.get(f"/chat/api/turn-traces/{trace.id}", headers=auth_headers)).json()

    assert trace.context_snapshot_json["turn_id"] == "turn-2"
    assert [call["tokens"]["input"] for call in body["calls"]] == [33, 44]
    assert body["promptOnDevice"] is False


@pytest.mark.asyncio
async def test_registration_with_a_job_names_the_jobs_current_turn_on_the_gateway_session(client, db):
    workspace_id = await seed_workspace(db)
    user_id = await seed_member(db, workspace_id=workspace_id, role="member")
    other_id = await seed_member(db, workspace_id=workspace_id, role="member")
    chat = await _thread(db, user_id)
    job = await _device_job(db, user_id, chat, claude_session=None)
    grant = OAuthGrant(id=str(uuid.uuid4()), user_id=user_id, client_id="octryx-claude-test", scopes=[SCOPE_MODEL_INVOKE])
    db.add(grant)
    await db.commit()
    token, _ = mint_access_token(user_id=user_id, client_id=grant.client_id, grant_id=grant.id,
                                 scopes=[SCOPE_MODEL_INVOKE], resource=GATEWAY_AUDIENCE)
    key = str(uuid.uuid4())
    headers = {"authorization": f"Bearer {token}", "x-octryx-workspace": workspace_id,
               "x-octryx-session": key}

    answer = await client.post("/api/v1/agent-gateway/sessions/register", headers=headers,
                               json={"profile": "governed", "client": "octryx-claude", "job_id": job.id})

    assert answer.status_code == 200, answer.text
    gateway = (await db.execute(select(AgentSession).where(
        AgentSession.metadata_["gateway_session_key"].as_string() == key))).scalar_one()
    await db.refresh(gateway)
    assert (gateway.metadata_[GATEWAY_JOB_KEY], gateway.metadata_[GATEWAY_TURN_KEY]) == (job.id, "turn-1")
    # Someone else's job is never stamped on a session.
    foreign = await _thread(db, other_id)
    await stamp_gateway_session(db, foreign, job.id, other_id)
    assert GATEWAY_JOB_KEY not in foreign.metadata_
