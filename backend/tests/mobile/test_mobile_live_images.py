"""Octryx Mobile "live" pictures: the person sends screenshots to a session.

A message may carry up to three PNG, JPEG or WebP pictures (checked by their bytes). The channel sends them in
chunks before the ``live_send`` that names them; once the device settles the message, the platform deletes them.
"""

from __future__ import annotations

import base64
import hashlib

import pytest
from sqlalchemy import select

from app.models import LiveAttachment, LiveMessage
from app.services.devices.jobs_channel import DeviceJobHandlers
from app.services.devices.live_values import CHUNK_BYTES, IMAGE_TEXT, MAX_IMAGE_BYTES, image_type
from tests.devices.device_support import RecordingConnection
from tests.mobile.mobile_live_support import cookie_client  # noqa: F401 - fixture
from tests.mobile.test_mobile_live import PEER, _admin, _reporting_device

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
JPEG_BIG = b"\xff\xd8\xff\xe0" + bytes(range(256)) * ((CHUNK_BYTES * 2) // 256 + 3)  # three chunks


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode()


@pytest.mark.asyncio
async def test_pictures_go_to_the_device_in_chunks_and_are_deleted_when_settled(cookie_client, db):  # noqa: F811
    owner = await _admin(db)
    device = await _reporting_device(db, owner)
    sent = await cookie_client.post("/api/v1/mobile/live/messages", json={
        "device_id": device.id, "peer": PEER, "text": "",
        "images": [{"data": _b64(PNG)}, {"data": _b64(JPEG_BIG)}]})
    assert sent.status_code == 202, sent.text
    message = sent.json()["message"]
    assert message["text"] == IMAGE_TEXT and message["attachments"] == 2

    connection = RecordingConnection(device.id)
    handlers = DeviceJobHandlers()
    await handlers.tick(db, connection)
    await db.commit()
    kinds = [kind for kind, _ in connection.sent]
    assert kinds.index("live_send") == len(kinds) - 1  # every chunk before the message that names them
    chunks = [body for kind, body in connection.sent if kind == "live_attachment"]
    [live_send] = [body for kind, body in connection.sent if kind == "live_send"]
    named = live_send["attachments"]
    assert [item["media_type"] for item in named] == ["image/png", "image/jpeg"]
    for item, original in zip(named, (PNG, JPEG_BIG), strict=True):
        parts = sorted((c for c in chunks if c["attachment_id"] == item["id"]), key=lambda c: c["index"])
        assert {c["total"] for c in parts} == {len(parts)}
        joined = b"".join(base64.b64decode(c["data"]) for c in parts)
        assert joined == original and item["sha256"] == hashlib.sha256(original).hexdigest()
        assert item["size"] == len(original)
    assert max(len(c["data"]) for c in chunks) < 220 * 1024  # well inside the channel's 256 KiB

    await handlers.message(db, connection, {"type": "live_delivery", "body": {
        "message_id": message["id"], "state": "delivered", "reason": ""}})
    await db.commit()
    assert (await db.execute(select(LiveAttachment))).scalars().all() == []
    stored = await db.get(LiveMessage, message["id"])
    assert stored.attachment_count == 2 and stored.state == "delivered"


@pytest.mark.asyncio
async def test_a_device_answer_naming_a_missing_picture_settles_as_failed(cookie_client, db):  # noqa: F811
    owner = await _admin(db)
    device = await _reporting_device(db, owner)
    sent = await cookie_client.post("/api/v1/mobile/live/messages", json={
        "device_id": device.id, "peer": PEER, "text": "look", "images": [{"data": _b64(PNG)}]})
    message_id = sent.json()["message"]["id"]
    connection = RecordingConnection(device.id)
    handlers = DeviceJobHandlers()
    await handlers.tick(db, connection)
    await handlers.message(db, connection, {"type": "live_delivery", "body": {
        "message_id": message_id, "state": "failed", "reason": "attachment_missing"}})
    await db.commit()
    stored = await db.get(LiveMessage, message_id)
    assert (stored.state, stored.reason) == ("failed", "attachment_missing")
    assert (await db.execute(select(LiveAttachment))).scalars().all() == []


@pytest.mark.asyncio
async def test_only_real_pictures_few_and_small_enough(cookie_client, db):  # noqa: F811
    owner = await _admin(db)
    device = await _reporting_device(db, owner)

    async def send(images):
        return await cookie_client.post("/api/v1/mobile/live/messages", json={
            "device_id": device.id, "peer": PEER, "text": "x", "images": images})

    assert (await send([{"data": _b64(b"<svg onload=alert(1)>")}])).json()["reason"] == "image_type_refused"
    assert (await send([{"data": _b64(b"%PDF-1.7 ...")}])).json()["reason"] == "image_type_refused"
    assert (await send([{"data": "not base64!!"}])).json()["reason"] == "images_invalid"
    assert (await send([{"data": _b64(PNG)}] * 4)).json()["reason"] == "images_invalid"
    assert (await send("nope")).json()["reason"] == "images_invalid"
    too_big = PNG + b"\x00" * MAX_IMAGE_BYTES
    assert (await send([{"data": _b64(too_big)}])).status_code == 413
    assert (await db.execute(select(LiveMessage))).scalars().all() == []
    assert (await db.execute(select(LiveAttachment))).scalars().all() == []


def test_picture_types_come_from_the_bytes():
    assert image_type(PNG) == "image/png"
    assert image_type(b"\xff\xd8\xff\xdb....") == "image/jpeg"
    assert image_type(b"RIFF\x00\x00\x00\x00WEBPVP8 ") == "image/webp"
    assert image_type(b"GIF89a") == ""
    assert image_type(b"") == ""
