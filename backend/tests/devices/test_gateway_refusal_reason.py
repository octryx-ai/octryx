from __future__ import annotations

from types import SimpleNamespace

import pytest

from app import db as db_core
from app.models import DeviceJob, Session
from app.services.agent_gateway.contract import HEADER_GATEWAY_REASON, HEADER_GATEWAY_STATE
from app.services.devices.job_events import apply_event
from app.services.model_gateway.inbound.refusal_note import KEY, note_refusal
from tests.devices.device_support import chat_session, device_with_grant, user_named

REASON = "data_classification_unresolved"
CONNECTION_FAILED = "codex_error_httpConnectionFailed"


@pytest.fixture(autouse=True)
def note_on_test_session(db, monkeypatch):
    class Shared:
        async def __aenter__(self):
            return db

        async def __aexit__(self, *exc):
            return None

    monkeypatch.setattr(db_core, "async_session_factory", Shared)


def _response(status: int, reason: str = REASON, state: str = "denied") -> SimpleNamespace:
    return SimpleNamespace(status_code=status, headers={HEADER_GATEWAY_REASON: reason, HEADER_GATEWAY_STATE: state})


async def _job(db) -> DeviceJob:
    user = await user_named(db, "refused-owner")
    device, _grant = await device_with_grant(db, user)
    session = await chat_session(db, user)
    job = DeviceJob(device_id=device.id, owner_user_id=user.id, session_id=session.id, workspace_id=session.project_id,
                    folder="/workspace/r1", profile="governed", status="offered", turn_id="t1", turn_state="sent")
    db.add(job)
    await db.flush()
    return job


async def _failed(db, job: DeviceJob, **body) -> None:
    await apply_event(db, job, "turn_finished", {"turn_id": job.turn_id, "status": "error", **body}, limits={})


@pytest.mark.asyncio
async def test_a_refused_turn_names_the_gateways_reason(db):
    job = await _job(db)
    await apply_event(db, job, "job_accepted", {"turn_id": "t1"}, limits={})
    await note_refusal(job.session_id, _response(403))
    await _failed(db, job, error=CONNECTION_FAILED)
    assert job.status_reason == REASON


@pytest.mark.asyncio
async def test_a_claude_code_turn_that_reports_no_code_names_the_gateways_reason(db):
    job = await _job(db)
    await apply_event(db, job, "job_accepted", {"turn_id": "t1"}, limits={})
    await note_refusal(job.session_id, _response(403, state="needs_configuration", reason="alias_not_listed"))
    await _failed(db, job)
    assert job.status_reason == "alias_not_listed"


@pytest.mark.asyncio
async def test_the_devices_own_code_wins_over_a_noted_refusal(db):
    job = await _job(db)
    await apply_event(db, job, "job_accepted", {"turn_id": "t1"}, limits={})
    await note_refusal(job.session_id, _response(403))
    await _failed(db, job, reason="service_restarted")
    assert job.status_reason == "service_restarted"  # a restart is still retried, never paused for a person


@pytest.mark.asyncio
async def test_a_refusal_of_an_earlier_turn_never_names_the_next_one(db):
    job = await _job(db)
    await note_refusal(job.session_id, _response(403))
    await apply_event(db, job, "job_accepted", {"turn_id": "t1"}, limits={})  # a new turn starts clean
    session = await db.get(Session, job.session_id)
    assert KEY not in dict(session.metadata_ or {})
    await _failed(db, job, error=CONNECTION_FAILED)
    assert job.status_reason == CONNECTION_FAILED


@pytest.mark.asyncio
async def test_only_the_gateways_own_refusals_are_noted(db):
    job = await _job(db)
    await apply_event(db, job, "job_accepted", {"turn_id": "t1"}, limits={})
    for response in (_response(200), _response(403, reason=""), SimpleNamespace(status_code=403, headers=None),
                     _response(429, reason="upstream_status_429", state="rate_limited"),  # the engine retries
                     _response(529, reason="upstream_status_529", state="needs_configuration"),
                     _response(400, reason="upstream_status_400", state="context_pressure"),  # the engine compacts
                     _response(404, reason="count_tokens_not_supported", state="needs_configuration")):
        await note_refusal(job.session_id, response)
    session = await db.get(Session, job.session_id)
    assert KEY not in dict(session.metadata_ or {})
    await note_refusal("", _response(403))  # no session: nothing to note, no error
    await _failed(db, job, reason="service_restarted")
    assert job.status_reason == "service_restarted"


@pytest.mark.asyncio
async def test_a_refusal_on_the_gateways_own_session_reaches_the_job_of_its_turn(db):
    job = await _job(db)
    chat = await db.get(Session, job.session_id)
    gateway = Session(user_id=chat.user_id, project_id=chat.project_id, origin="model_gateway",
                      metadata_={"device_job_id": job.id, "device_turn_id": "t1"})
    db.add(gateway)
    await db.flush()
    await apply_event(db, job, "job_accepted", {"turn_id": "t1"}, limits={})
    await note_refusal(gateway.id, _response(403, reason="alias_not_listed"))
    await _failed(db, job, error=CONNECTION_FAILED)
    assert job.status_reason == "alias_not_listed"

    job.turn_id = "t2"  # a later turn never takes an earlier turn's refusal
    await _failed(db, job, error=CONNECTION_FAILED)
    assert job.status_reason == CONNECTION_FAILED


@pytest.mark.asyncio
async def test_a_failed_note_leaves_the_requests_own_session_alone(db, monkeypatch):
    job = await _job(db)
    chat = await db.get(Session, job.session_id)
    chat.metadata_ = {**dict(chat.metadata_ or {}), "pending": "kept"}  # the request's own unflushed write

    def broken():
        raise RuntimeError("no database")

    monkeypatch.setattr(db_core, "async_session_factory", broken)
    await note_refusal(job.session_id, _response(403))  # logged, never raised, nothing rolled back
    assert chat in db and chat.metadata_["pending"] == "kept" and chat in db.dirty
