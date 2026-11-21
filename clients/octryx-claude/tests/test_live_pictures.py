"""Pictures from the phone (a screenshot could not be sent before): the service joins the
chunks, checks size, hash and type, writes the picture privately and hands the session its path."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import stat

import pytest

from octryx_claude import live_attachments
from tests.live_sessions_support import SESSION, _bridge, _FakeRelay

PNG = b"\x89PNG\r\n\x1a\n" + bytes(range(256)) * 10


@pytest.fixture(autouse=True)
def private_inbox(tmp_path, monkeypatch):
    inbox = tmp_path / "inbox-root" / "octryx-inbox"
    monkeypatch.setattr(live_attachments, "inbox_dir", lambda: inbox)
    return inbox


def _chunks(message_id: str, attachment_id: str, data: bytes, size: int = 1000):
    parts = [data[i:i + size] for i in range(0, len(data), size)]
    return [{"message_id": message_id, "attachment_id": attachment_id, "index": index, "total": len(parts),
             "data": base64.b64encode(part).decode()} for index, part in enumerate(parts)]


def _named(attachment_id: str, data: bytes, media_type: str = "image/png"):
    return {"id": attachment_id, "media_type": media_type, "size": len(data),
            "sha256": hashlib.sha256(data).hexdigest()}


def test_a_picture_lands_privately_and_the_session_gets_its_path(tmp_path, private_inbox):
    bridge, channel = _bridge(tmp_path, True, [SESSION])

    async def scenario() -> None:
        for chunk in reversed(_chunks("m1", "la_1", PNG)):  # order of arrival does not matter
            await bridge.handle("live_attachment", chunk)
        await bridge.handle("live_send", {"message_id": "m1", "peer": SESSION["peer"], "text": "Look at this",
                                          "sender": "L", "attachments": [_named("la_1", PNG)]})

    asyncio.run(scenario())
    [(peer, text, _sender, key)] = _FakeRelay.instances[0].sends
    path = private_inbox / "m1-1.png"
    assert peer == SESSION["peer"] and key == "m1"
    assert text.startswith("Look at this\n\n[The phone attached 1 picture. Open with the Read tool:]")
    assert str(path) in text
    assert path.read_bytes() == PNG
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert stat.S_IMODE(private_inbox.stat().st_mode) == 0o700
    assert not [body for kind, body in channel.sent if kind == "live_delivery"]  # the relay settles it later


@pytest.mark.parametrize("problem", ["missing_chunk", "wrong_hash", "not_a_picture", "type_mismatch", "unknown_id"])
def test_a_missing_or_wrong_picture_fails_the_message_and_delivers_nothing(tmp_path, private_inbox, problem):
    bridge, channel = _bridge(tmp_path, True, [SESSION])
    data = b"%PDF-1.7 not a picture" * 40 if problem == "not_a_picture" else PNG
    chunks = _chunks("m1", "la_1", data)
    named = _named("la_1", data)
    if problem == "missing_chunk":
        chunks = chunks[1:]
    elif problem == "wrong_hash":
        named["sha256"] = "0" * 64
    elif problem == "type_mismatch":
        named["media_type"] = "image/jpeg"
    elif problem == "unknown_id":
        named["id"] = "la_other"

    async def scenario() -> None:
        for chunk in chunks:
            await bridge.handle("live_attachment", chunk)
        await bridge.handle("live_send", {"message_id": "m1", "peer": SESSION["peer"], "text": "x",
                                          "sender": "L", "attachments": [named]})

    asyncio.run(scenario())
    assert _FakeRelay.instances == [] or _FakeRelay.instances[0].sends == []
    assert [body for kind, body in channel.sent if kind == "live_delivery"] == [
        {"message_id": "m1", "state": "failed", "reason": "attachment_missing"}]
    assert not private_inbox.exists() or list(private_inbox.iterdir()) == []


def test_chunk_limits_keep_memory_bounded(tmp_path):
    bridge, _ = _bridge(tmp_path, True, [SESSION])
    big = b"\x00" * (live_attachments.MAX_ATTACHMENT_BYTES // 2 + 10)
    chunk = {"message_id": "m1", "attachment_id": "la_big", "total": 3, "data": base64.b64encode(big).decode()}
    bridge._attachment({**chunk, "index": 0})
    bridge._attachment({**chunk, "index": 1})  # over the per-picture limit: the whole picture is dropped
    assert "la_big" not in bridge._parts
    bridge._attachment({**chunk, "index": 5})  # index outside total: ignored
    bridge._attachment({**chunk, "total": live_attachments.MAX_ATTACHMENT_PARTS + 1, "index": 0})
    assert bridge._parts == {}
    for number in range(live_attachments.MAX_PENDING_ATTACHMENTS + 3):
        bridge._attachment({"message_id": "m1", "attachment_id": f"la_{number}", "index": 0, "total": 2,
                            "data": base64.b64encode(b"x").decode()})
    assert len(bridge._parts) == live_attachments.MAX_PENDING_ATTACHMENTS
    assert "la_0" not in bridge._parts  # the oldest went first


def test_old_pictures_are_cleaned_from_the_inbox(tmp_path, private_inbox):
    import os
    import time

    private_inbox.mkdir(parents=True)
    old = private_inbox / "old-1.png"
    old.write_bytes(PNG)
    past = time.time() - live_attachments.INBOX_KEEP_SECONDS - 60
    os.utime(old, (past, past))
    bridge, _ = _bridge(tmp_path, True, [SESSION])

    async def scenario() -> None:
        for chunk in _chunks("m2", "la_2", PNG):
            await bridge.handle("live_attachment", chunk)
        await bridge.handle("live_send", {"message_id": "m2", "peer": SESSION["peer"], "text": "(picture)",
                                          "sender": "L", "attachments": [_named("la_2", PNG)]})

    asyncio.run(scenario())
    assert not old.exists()
    assert (private_inbox / "m2-1.png").exists()
