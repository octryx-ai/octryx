"""Files a device job made on the Mac: fetched only on the owner's request, only listed paths, checked transfers,
served so they never run as a page on the platform."""

from __future__ import annotations

import base64
import hashlib
from datetime import timedelta

import pytest
from sqlalchemy import select

from app.auth_cookie_policy import ACCESS_TOKEN_COOKIE
from app.models import DeviceJob, DeviceJobEvent, DeviceJobFile, User
from app.services.devices.jobs_channel import DeviceJobHandlers
from app.time_utils import utc_now
from tests.conftest import ADMIN_PASSWORD
from tests.devices.device_support import RecordingConnection, chat_session, device_with_grant, user_named


@pytest.fixture
async def cookie_client(client):
    login = await client.post("/api/v1/auth/login", data={"username": "admin", "password": ADMIN_PASSWORD})
    assert login.status_code == 200, login.text
    client.cookies.set(ACCESS_TOKEN_COOKIE, login.json()["access_token"])
    yield client
    client.cookies.clear()


async def _job_with_files(db, user, paths=("out/report.md", "chart.png", "page.html")):
    device, _ = await device_with_grant(db, user)
    session = await chat_session(db, user)
    job = DeviceJob(device_id=device.id, owner_user_id=user.id, session_id=session.id, folder="/home/sample/src",
                    profile="governed", status="idle")
    db.add(job)
    await db.flush()
    db.add(DeviceJobEvent(job_id=job.id, seq=1, type="job_event",
                          body={"kind": "files", "files": [{"path": p, "size": 5, "mtime": 1} for p in paths]}))
    job.last_event_seq = 1
    await db.commit()
    return device.id, job.id


async def _transfer(db, handlers, device_id, request_id, data: bytes, chunk=4):
    connection = RecordingConnection(device_id)
    parts = [data[i:i + chunk] for i in range(0, len(data), chunk)] or [b""]
    for seq, part in enumerate(parts):
        body = {"request_id": request_id, "seq": seq, "data": base64.b64encode(part).decode(), "last": False}
        if seq == len(parts) - 1:
            body.update(last=True, size=len(data), sha256=hashlib.sha256(data).hexdigest())
        await handlers.message(db, connection, {"type": "file_chunk", "body": body})
    await db.commit()


async def _admin(db) -> User:
    return (await db.execute(select(User).where(User.username == "admin"))).scalar_one()


@pytest.mark.asyncio
async def test_owner_fetches_a_listed_file_from_the_mac(cookie_client, db):
    device_id, job_id = await _job_with_files(db, await _admin(db))
    asked = await cookie_client.post(f"/api/v1/device-jobs/{job_id}/files", json={"path": "out/report.md"})
    assert asked.status_code == 202, asked.text
    file_id = asked.json()["file"]["id"]

    handlers = DeviceJobHandlers()
    connection = RecordingConnection(device_id)
    await handlers.tick(db, connection)
    await db.commit()
    assert ("file_request", {"request_id": file_id, "job_id": job_id, "path": "out/report.md"}) in connection.sent

    await _transfer(db, handlers, device_id, file_id, b"# Report\nall green\n")
    state = await cookie_client.get(f"/api/v1/device-jobs/{job_id}/files/{file_id}")
    assert state.json()["file"]["state"] == "ready" and state.json()["file"]["size"] == 19
    content = await cookie_client.get(f"/api/v1/device-jobs/{job_id}/files/{file_id}/content")
    assert content.status_code == 200 and content.content == b"# Report\nall green\n"
    assert content.headers["content-type"].startswith("text/plain")
    assert content.headers["x-content-type-options"] == "nosniff"
    assert "sandbox" in content.headers["content-security-policy"]


@pytest.mark.asyncio
async def test_html_is_never_rendered_and_downloads_are_attachments(cookie_client, db):
    device_id, job_id = await _job_with_files(db, await _admin(db))
    handlers = DeviceJobHandlers()
    ids = {}
    for path in ("page.html", "chart.png"):
        ids[path] = (await cookie_client.post(f"/api/v1/device-jobs/{job_id}/files", json={"path": path})
                     ).json()["file"]["id"]
    await handlers.tick(db, RecordingConnection(device_id))
    await db.commit()
    await _transfer(db, handlers, device_id, ids["page.html"], b"<script>alert(1)</script>")
    await _transfer(db, handlers, device_id, ids["chart.png"], b"\x89PNG....")
    page = await cookie_client.get(f"/api/v1/device-jobs/{job_id}/files/{ids['page.html']}/content")
    assert page.headers["content-type"].startswith("text/plain")
    image = await cookie_client.get(f"/api/v1/device-jobs/{job_id}/files/{ids['chart.png']}/content")
    assert image.headers["content-type"] == "image/png"
    download = await cookie_client.get(f"/api/v1/device-jobs/{job_id}/files/{ids['page.html']}/content",
                                       params={"download": "true"})
    assert download.headers["content-type"] == "application/octet-stream"
    assert download.headers["content-disposition"].startswith("attachment;")


@pytest.mark.asyncio
async def test_refusals(cookie_client, client, db, auth_headers):
    owner = await _admin(db)
    device_id, job_id = await _job_with_files(db, owner)
    _, foreign_job = await _job_with_files(db, await user_named(db, "someone"))

    async def ask(job=job_id, path="out/report.md", **kw):
        return await cookie_client.post(f"/api/v1/device-jobs/{job}/files", json={"path": path}, **kw)

    assert (await ask(path="../../etc/passwd")).json()["reason"] == "file_not_listed"
    assert (await ask(path=".env")).json()["reason"] == "file_not_listed"
    assert (await ask(job=foreign_job)).json()["reason"] == "device_job_not_found"
    cookie_client.cookies.clear()
    bearer = await client.post(f"/api/v1/device-jobs/{job_id}/files", headers=auth_headers,
                               json={"path": "out/report.md"})
    assert bearer.status_code == 403 and bearer.json()["reason"] == "interactive_login_required"
    assert (await db.execute(select(DeviceJobFile))).scalars().all() == []


@pytest.mark.asyncio
async def test_bad_transfers_fail_and_requests_time_out(cookie_client, db):
    device_id, job_id = await _job_with_files(db, await _admin(db))
    handlers = DeviceJobHandlers()
    first = (await cookie_client.post(f"/api/v1/device-jobs/{job_id}/files", json={"path": "out/report.md"})
             ).json()["file"]["id"]
    second = (await cookie_client.post(f"/api/v1/device-jobs/{job_id}/files", json={"path": "chart.png"})
              ).json()["file"]["id"]
    third = (await cookie_client.post(f"/api/v1/device-jobs/{job_id}/files", json={"path": "page.html"})
             ).json()["file"]["id"]
    await handlers.tick(db, RecordingConnection(device_id))
    await db.commit()

    # A wrong checksum, another device's chunk, the device's own refusal.
    connection = RecordingConnection(device_id)
    await handlers.message(db, connection, {"type": "file_chunk", "body": {
        "request_id": first, "seq": 0, "data": base64.b64encode(b"abc").decode(), "last": True, "size": 3,
        "sha256": "0" * 64}})
    other_device, _ = await device_with_grant(db, await _admin(db), name="Other")
    await handlers.message(db, RecordingConnection(other_device.id), {"type": "file_failed", "body": {
        "request_id": second, "reason": "secret_file"}})
    await handlers.message(db, connection, {"type": "file_failed", "body": {"request_id": third,
                                                                            "reason": "secret_file"}})
    await db.commit()
    rows = {row.id: row for row in (await db.execute(select(DeviceJobFile))).scalars().all()}
    assert (rows[first].state, rows[first].reason) == ("failed", "transfer_invalid")
    assert rows[second].state == "sent"
    assert (rows[third].state, rows[third].reason) == ("failed", "secret_file")
    assert rows[first].content is None

    rows[second].updated_at = utc_now() - timedelta(minutes=5)
    await handlers.tick(db, connection)
    await db.commit()
    assert (await db.get(DeviceJobFile, second)).reason == "no_answer"


@pytest.mark.asyncio
async def test_expired_files_are_purged_without_a_new_request(cookie_client, db):
    """The housekeeping deletes a day-old file even if its owner never asks again."""
    from app.services.devices.job_files import purge_expired

    device_id, job_id = await _job_with_files(db, await _admin(db))
    owner = await _admin(db)
    db.add_all([
        DeviceJobFile(job_id=job_id, device_id=device_id, owner_user_id=owner.id, path="out/report.md",
                      state="ready", content=b"old", created_at=utc_now() - timedelta(days=2),
                      updated_at=utc_now() - timedelta(days=2)),
        DeviceJobFile(job_id=job_id, device_id=device_id, owner_user_id=owner.id, path="chart.png", state="ready",
                      content=b"new", created_at=utc_now(), updated_at=utc_now()),
    ])
    await db.commit()
    assert await purge_expired(db) == 1
    assert [row.path for row in (await db.execute(select(DeviceJobFile))).scalars().all()] == ["chart.png"]
