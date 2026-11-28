"""A turn's engine files: stored encrypted by the job's device, read back only by the device that runs the thread's
active job, carried to a turn on another device with its resume id."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from sqlalchemy import select

from app.models import AuditLog, Session
from app.services.artifact_store import service as artifact_service
from app.services.devices import engine_state
from app.services.devices.jobs import start_turn
from app.services.devices.jobs_channel import DeviceJobHandlers
from app.services.secret.crypto import decrypt_bytes
from app.services.workflow_runs.octryx.phase_sessions import _session_here
from tests.devices.device_support import (
    RecordingConnection,
    chat_session,
    keyed_device,
    member_with_headers,
    user_named,
)

FOLDER = "/home/sample/src"
PLAIN = b'{"type":"user","message":"the secret plan"}\n' * 20


@pytest.fixture(autouse=True)
def artifact_dir(tmp_path, monkeypatch) -> Path:
    monkeypatch.setattr(artifact_service.settings, "artifact_store_dir", str(tmp_path))
    monkeypatch.setattr(artifact_service.settings, "artifact_store_backend", "filesystem")
    return tmp_path


async def _setup(db):
    user = await user_named(db, "state-owner")
    mac, _private, mac_token = await keyed_device(db, user, name="Mac")
    other, _private, other_token = await keyed_device(db, user, name="Other")
    thread = await chat_session(db, user)
    job = await start_turn(db, owner_user_id=user.id, device=mac, session_id=thread.id,
                           workspace_id=thread.project_id, folder=FOLDER, profile="governed", prompt="Build")
    return user, (mac, mac_token), (other, other_token), thread, job


async def _put(client, job, token, data, *, sha=None, size=None, session="cs-1"):
    params = {"engine": "claude_code", "engine_session_id": session, "turn_id": job.turn_id,
              "sha256": sha or hashlib.sha256(data).hexdigest(), "bytes": len(data) if size is None else size}
    return await client.put(f"/api/v1/devices/jobs/{job.id}/session-state", params=params, content=data,
                            headers={"Authorization": f"Bearer {token}"})


async def _get(client, job, headers):
    return await client.get(f"/api/v1/devices/jobs/{job.id}/session-state", headers=headers)


async def test_the_jobs_device_stores_encrypted_and_only_it_reads_back(client, db, artifact_dir):
    _user, (_mac, mac_token), (_other, other_token), thread, job = await _setup(db)
    response = await _put(client, job, mac_token, PLAIN)
    assert response.status_code == 200, response.text
    state = engine_state.snapshot_of(await db.get(Session, thread.id))
    assert (state["engine"], state["engine_session_id"], state["bytes"]) == ("claude_code", "cs-1", len(PLAIN))
    stored = (artifact_dir / state["location"]).read_bytes()
    assert b"secret plan" not in stored and decrypt_bytes(stored) == PLAIN

    fetched = await _get(client, job, {"Authorization": f"Bearer {mac_token}"})
    assert fetched.status_code == 200 and fetched.content == PLAIN
    assert fetched.headers["x-octryx-sha256"] == hashlib.sha256(PLAIN).hexdigest()
    _person, person_headers = await member_with_headers(client, db, "state-person")
    for headers in ({"Authorization": f"Bearer {other_token}"}, person_headers, {}):
        assert (await _get(client, job, headers)).status_code == 404
    assert (await _put(client, job, other_token, PLAIN)).status_code == 404


async def test_a_wrong_digest_or_an_oversized_state_keeps_the_previous_snapshot(client, db, monkeypatch):
    _user, (_mac, mac_token), _other, thread, job = await _setup(db)
    assert (await _put(client, job, mac_token, PLAIN)).status_code == 200
    before = engine_state.snapshot_of(await db.get(Session, thread.id))

    refused = await _put(client, job, mac_token, b"other bytes", sha="0" * 64)
    assert refused.status_code == 400 and refused.json()["reason"] == "session_state_digest_mismatch"
    monkeypatch.setattr(engine_state, "MAX_STATE_BYTES", 64)
    too_large = await _put(client, job, mac_token, b"x" * 65, session="cs-2")
    declared = await _put(client, job, mac_token, b"", size=10_000, session="cs-2")
    assert [too_large.status_code, declared.status_code] == [413, 413]
    assert too_large.json()["reason"] == "session_state_too_large"
    assert engine_state.snapshot_of(await db.get(Session, thread.id)) == before
    actions = (await db.execute(select(AuditLog.action).where(AuditLog.resource_id == job.id))).scalars().all()
    assert actions.count("device.job.session_state_too_large") == 2
    fetched = await _get(client, job, {"Authorization": f"Bearer {mac_token}"})
    assert fetched.content == PLAIN


async def test_a_turn_on_another_device_resumes_the_snapshots_session_and_the_offer_names_it(client, db):
    user, (mac, mac_token), (other, _token), thread, job = await _setup(db)
    handlers = DeviceJobHandlers()
    await handlers.tick(db, RecordingConnection(mac.id))
    assert (await _put(client, job, mac_token, PLAIN)).status_code == 200
    job.claude_session_id, job.status, job.turn_state = "cs-1", "idle", "done"
    await db.flush()

    moved = await start_turn(db, owner_user_id=user.id, device=other, session_id=thread.id,
                             workspace_id=thread.project_id, folder="/home/sample/other", profile="governed",
                             prompt="Go on")
    assert moved.id != job.id and moved.resume_claude_session_id == "cs-1"
    connection = RecordingConnection(other.id)
    await handlers.tick(db, connection)
    (_kind, offer), = connection.sent
    assert offer["resume_session_id"] == "cs-1" and offer["engine"] == "claude_code"
    assert offer["session_state"] == {"sha256": hashlib.sha256(PLAIN).hexdigest(), "engine": "claude_code",
                                      "engine_session_id": "cs-1"}
    entry = {"device_id": mac.id, "folder": FOLDER, "profile": "governed", "claude_session_id": "cs-1",
             "job_id": job.id, "turn_id": job.turn_id}
    target = {"device_id": other.id, "folder": "/home/sample/other", "profile": "governed"}
    assert await _session_here(db, entry, target) == "cs-1"
    assert await _session_here(db, {**entry, "claude_session_id": "cs-9"}, target) == ""


async def test_without_a_snapshot_another_device_starts_fresh(db):
    user = await user_named(db, "fresh-owner")
    mac, _p, _t = await keyed_device(db, user, name="Mac")
    other, _p, _t = await keyed_device(db, user, name="Other")
    thread = await chat_session(db, user)
    first = await start_turn(db, owner_user_id=user.id, device=mac, session_id=thread.id,
                             workspace_id=thread.project_id, folder=FOLDER, profile="governed", prompt="Build")
    first.claude_session_id, first.status = "cs-1", "idle"
    await db.flush()
    moved = await start_turn(db, owner_user_id=user.id, device=other, session_id=thread.id,
                             workspace_id=thread.project_id, folder=FOLDER, profile="governed", prompt="Go on")
    assert moved.resume_claude_session_id is None
    assert await engine_state.offer_session_state(db, moved) is None
