"""Full session transcripts per Workspace switch."""

# ruff: noqa: F811  (the shared ``artifact_dir`` fixture is imported, then requested by name)
from __future__ import annotations

import gzip
from datetime import timedelta

import pytest
from sqlalchemy import select

from app.models import AuditLog, SessionTranscriptChunk
from app.services.session_transcripts.retention import purge_expired
from app.time_utils import utc_now
from tests.agent_gateway.seat_presence_support import POLICY as CLIENT_POLICY
from tests.agent_gateway.seat_presence_support import _bearer, _gateway_headers, _register, _workspace
from tests.knowledge_evidence_seed_support import seed_member
from tests.session_transcripts.transcript_store_support import artifact_dir  # noqa: F401 - autouse fixture

SWITCH = "/api/v1/workspaces/{}/agent-gateway/session-transcripts"
LIST = "/api/v1/workspaces/{}/session-transcripts"
READ = "/api/v1/session-transcripts/{}"
BATCH = "/api/v1/agent-gateway/sessions/transcript"
AWS_KEY = ("AKIAAB" + "CDEFGHIJKLMNOP")
GH_TOKEN = "ghp_" + "a1B2c3D4e5" * 4


async def _setup(client, db):
    workspace = await _workspace(db)
    owner = await seed_member(db, workspace_id=workspace, role="member", username="transcript-owner")
    admin = await seed_member(db, workspace_id=workspace, role="admin", username="transcript-admin")
    other = await seed_member(db, workspace_id=workspace, role="member", username="transcript-other")
    await db.commit()
    headers = await _gateway_headers(db, owner, workspace)
    assert (await _register(client, headers, profile="governed")).status_code == 200
    return workspace, owner, admin, other, headers


def _line(text: str, *, n: int = 0) -> dict:
    return {"type": "assistant", "uuid": f"u{n}", "message": {"role": "assistant",
                                                             "content": [{"type": "text", "text": text}]}}


async def _send(client, headers, *, stream="main", first_line=1, lines=None):
    body = {"claude_session_id": headers["x-octryx-session"], "stream": stream, "first_line": first_line,
            "lines": lines or [_line("hello", n=first_line)]}
    return await client.post(BATCH, json=body, headers=headers)


async def _switch_on(client, workspace, admin, **extra):
    answer = await client.put(SWITCH.format(workspace), json={"enabled": True, **extra}, headers=await _bearer(admin))
    assert answer.status_code == 200, answer.text
    return answer.json()


@pytest.mark.asyncio
async def test_switch_off_by_default_stores_nothing(client, db, artifact_dir):
    workspace, owner, _admin, _other, headers = await _setup(client, db)
    shown = (await client.get(SWITCH.format(workspace), headers=await _bearer(owner))).json()
    assert shown == {"project_id": workspace, "session_transcripts": {"enabled": False, "retention_days": 30},
                     "source": "default", "can_edit": False}
    policy = (await client.get(CLIENT_POLICY, headers=headers)).json()
    assert policy["session_transcripts"] == {"enabled": False}

    answer = await _send(client, headers)
    assert answer.status_code == 200 and answer.json() == {"state": "off"}
    assert (await db.execute(select(SessionTranscriptChunk))).scalars().all() == []
    assert not any(artifact_dir.rglob("*.jsonl.gz"))


@pytest.mark.asyncio
async def test_admin_switches_on_audited_and_batches_store_main_and_subagents_once(client, db):
    workspace, owner, admin, _other, headers = await _setup(client, db)
    refused = await client.put(SWITCH.format(workspace), json={"enabled": True}, headers=await _bearer(owner))
    assert refused.status_code == 403
    assert (await client.put(SWITCH.format(workspace), json={"retention_days": 0},
                             headers=await _bearer(admin))).status_code == 422
    shown = await _switch_on(client, workspace, admin, retention_days=7)
    assert shown["session_transcripts"] == {"enabled": True, "retention_days": 7} and shown["can_edit"] is True
    audit = (await db.execute(select(AuditLog).where(
        AuditLog.action == "admin.agent_gateway.session_transcripts_updated"))).scalars().all()
    assert len(audit) == 1 and audit[0].details["after"]["enabled"] is True and audit[0].user_id == admin
    assert (await client.get(CLIENT_POLICY, headers=headers)).json()["session_transcripts"] == {"enabled": True}

    first = await _send(client, headers, lines=[_line("one", n=1), _line("two", n=2)])
    assert first.json() == {"state": "stored", "stream": "main", "last_line": 2}
    again = await _send(client, headers, lines=[_line("one", n=1), _line("two", n=2)])
    assert again.json()["state"] == "duplicate"
    sub = await _send(client, headers, stream="agent-a161095550378ad66", lines=[_line("subagent work")])
    assert sub.json()["state"] == "stored"
    assert (await _send(client, headers, stream="../etc")).status_code == 400

    [item] = (await client.get(LIST.format(workspace), headers=await _bearer(owner))).json()["items"]
    assert [(s["stream"], s["lines"]) for s in item["streams"]] == [("main", 2), ("agent-a161095550378ad66", 1)]

    # Switched off while the session runs: the next batch is refused with ``off`` and stored nowhere.
    await client.put(SWITCH.format(workspace), json={"enabled": False}, headers=await _bearer(admin))
    assert (await _send(client, headers, first_line=3)).json() == {"state": "off"}
    assert len((await db.execute(select(SessionTranscriptChunk))).scalars().all()) == 2


@pytest.mark.asyncio
async def test_secrets_are_redacted_before_storage_and_file_contents_stay(client, db, artifact_dir):
    workspace, owner, admin, _other, headers = await _setup(client, db)
    await _switch_on(client, workspace, admin)
    file_text = "def total(items):\n    return sum(items)\n"
    secret_line = {"type": "user", "toolUseResult": {"file": {"content": file_text}},
                   "message": {"content": [{"type": "tool_result", "content": f"aws key {AWS_KEY} and {GH_TOKEN}"}]},
                   "env": {"password": "hunter2-very-secret"}}
    assert (await _send(client, headers, lines=[secret_line, _line("Authorization: Bearer abcdefghijklmnop1234")]
                        )).json()["state"] == "stored"
    stored = b"".join(gzip.decompress(path.read_bytes()) for path in artifact_dir.rglob("*.jsonl.gz"))
    for secret in (AWS_KEY, GH_TOKEN, "hunter2-very-secret", "abcdefghijklmnop1234"):
        assert secret.encode() not in stored
    assert b"return sum(items)" in stored

    page = (await client.get(READ.format(_session_id(item := await _item(client, workspace, owner))),
                             headers=await _bearer(owner))).json()
    assert item and page["redacted"] is True and [line["line"] for line in page["lines"]] == [1, 2]
    assert page["lines"][0]["entry"]["toolUseResult"]["file"]["content"] == file_text


async def _item(client, workspace, user):
    [item] = (await client.get(LIST.format(workspace), headers=await _bearer(user))).json()["items"]
    return item


def _session_id(item) -> str:
    return item["session_id"]


@pytest.mark.asyncio
async def test_only_workspace_admins_and_the_owner_read_and_every_read_is_audited(client, db):
    workspace, owner, admin, other, headers = await _setup(client, db)
    await _switch_on(client, workspace, admin)
    lines = [_line(f"line {n}", n=n) for n in range(1, 6)]
    await _send(client, headers, lines=lines)
    session_id = _session_id(await _item(client, workspace, owner))

    first = (await client.get(READ.format(session_id), params={"limit": 2}, headers=await _bearer(owner))).json()
    assert [line["line"] for line in first["lines"]] == [1, 2] and first["next_from_line"] == 3
    rest = (await client.get(READ.format(session_id), params={"from_line": 3, "limit": 10},
                             headers=await _bearer(admin))).json()
    assert [line["line"] for line in rest["lines"]] == [3, 4, 5] and rest["next_from_line"] is None

    assert (await client.get(READ.format(session_id), headers=await _bearer(other))).status_code == 404
    assert (await client.get(LIST.format(workspace), headers=await _bearer(other))).json()["items"] == []
    outsider_ws = await _workspace(db)
    outsider = await seed_member(db, workspace_id=outsider_ws, role="owner", username="transcript-outsider")
    await db.commit()
    assert (await client.get(LIST.format(workspace), headers=await _bearer(outsider))).status_code == 404
    assert (await client.get(READ.format(session_id), headers=await _bearer(outsider))).status_code == 404

    reads = (await db.execute(select(AuditLog).where(AuditLog.action == "session_transcript.read")
                              .order_by(AuditLog.created_at))).scalars().all()
    assert [(row.user_id, row.details["as"]) for row in reads] == [(owner, "owner"), (admin, "workspace_admin")]


@pytest.mark.asyncio
async def test_retention_purges_old_batches_with_their_objects(client, db, artifact_dir):
    workspace, owner, admin, _other, headers = await _setup(client, db)
    await _switch_on(client, workspace, admin, retention_days=3)
    await _send(client, headers, first_line=1)
    await _send(client, headers, first_line=2)
    old, recent = (await db.execute(select(SessionTranscriptChunk).order_by(SessionTranscriptChunk.first_line))
                   ).scalars().all()
    old.created_at = utc_now() - timedelta(days=4)
    old_object = artifact_dir / old.storage_location
    await db.commit()
    assert old_object.exists()

    assert await purge_expired(db) == 1
    remaining = (await db.execute(select(SessionTranscriptChunk))).scalars().all()
    assert [chunk.id for chunk in remaining] == [recent.id]
    assert not old_object.exists() and (artifact_dir / recent.storage_location).exists()
