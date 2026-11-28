from __future__ import annotations

import uuid

import pytest

from app.models import Session, SessionTranscriptChunk
from app.services.project.private_workspace import ensure_private_workspace
from tests.devices.device_support import user_named
from tests.knowledge_evidence_seed_support import seed_workspace
from tests.policy_engine_support import bearer
from tests.workspace_id_route_support import answer_text, stable_headers

pytestmark = pytest.mark.asyncio

READ = "/api/v1/session-transcripts/{}"


async def _stored_transcript(db, owner_id: str, project_id: str) -> str:
    session = Session(id=str(uuid.uuid4()), user_id=owner_id, project_id=project_id, origin="chat")
    db.add(session)
    await db.flush()
    db.add(SessionTranscriptChunk(project_id=project_id, session_id=session.id, owner_user_id=owner_id,
                                  claude_session_id="claude-1", stream="main", first_line=1, last_line=1,
                                  line_count=1, byte_size=10, storage_backend="local", storage_location="unused"))
    await db.commit()
    return session.id


async def test_a_non_member_gets_the_same_answer_for_a_stored_foreign_transcript_and_an_unknown_one(client, db,
                                                                                                    monkeypatch):
    from app.services.session_transcripts import access

    owner = await user_named(db, f"transcript-owner-{uuid.uuid4().hex[:6]}")
    outsider = await user_named(db, f"transcript-outsider-{uuid.uuid4().hex[:6]}")
    private = await ensure_private_workspace(db, owner)
    named = {"private": await _stored_transcript(db, owner.id, private.id),
             "shared": await _stored_transcript(db, owner.id, await seed_workspace(db)),
             "unknown": str(uuid.uuid4())}
    answers = {}
    for kind, session_id in named.items():
        response = await client.get(READ.format(session_id), headers=bearer(outsider.id))
        answers[kind] = (response.status_code, answer_text(response, session_id), stable_headers(response, session_id))
    assert answers["private"][0] == 404 and "transcript_not_found" in answers["private"][1], answers
    assert answers["private"] == answers["shared"] == answers["unknown"], answers

    async def _lines(_chunk):
        return [{"type": "assistant", "uuid": "u1"}]

    monkeypatch.setattr(access, "read_chunk_lines", _lines)
    response = await client.get(READ.format(named["private"]), headers=bearer(owner.id))
    assert response.status_code == 200 and response.json()["session_id"] == named["private"], response.text[:300]
