"""Summary updates store validated references with their evidence map and honour the cooldown, and the drill-back tool resolves message and tool-call references only inside its own session."""

import json
import uuid
from datetime import timedelta

import pytest
from sqlalchemy import select

from app.agent.core.runtime.summarizer import _update_summary
from app.models import Message, Session, User
from app.time_utils import utc_now
from app.tools.context import ToolContext
from app.tools.context_tools import GetSessionSummaryEvidenceTool

# ── _update_summary persistence + cooldown ───────────────────────────────────


class _RecordingProvider:
    def __init__(self, response_factory):
        self.calls = 0
        self.last_user_prompt = ""
        self._response_factory = response_factory

    async def chat(self, *, messages, model, temperature, max_tokens):
        del model, temperature, max_tokens
        self.calls += 1
        self.last_user_prompt = messages[-1]["content"]
        return {"content": self._response_factory(self.last_user_prompt)}


async def _seed_session(db, message_count=12):
    user = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    session = Session(id=str(uuid.uuid4()), user_id=user.id, agent_type="chat", status="active", metadata_={})
    db.add(session)
    messages = []
    base_time = utc_now()
    for idx in range(message_count):
        message = Message(
            id=str(uuid.uuid4()),
            session_id=session.id,
            role="user" if idx % 2 == 0 else "assistant",
            content=f"Message {idx} about payment-service OOMKilled.",
            created_at=base_time + timedelta(seconds=idx),
        )
        messages.append(message)
        db.add(message)
    await db.commit()
    return session, messages


# ── Drill-back tool ──────────────────────────────────────────────────────────


def _tool_context(db, session_id):
    return ToolContext(
        user_id="user-1",
        project_ids=[],
        roles=["admin"],
        session_id=session_id,
        project_config={},
        db=db,
    )


@pytest.mark.asyncio
async def test_update_summary_stores_validated_references_and_evidence_map(db, monkeypatch):
    from app.agent import providers as provider_module

    session, messages = await _seed_session(db)
    valid_ref = f"msg:{messages[0].id}"

    def _respond(user_prompt):
        assert valid_ref in user_prompt  # evidence list is offered to the model
        return json.dumps(
            {
                "goal": "Analyse OOM crash",
                "findings": [{"type": "root_cause", "text": f"OOMKilled seen [{valid_ref}] [msg:hallucinated]"}],
                "actions_taken": [],
                "open_items": [],
                "state": "in_progress",
            }
        )

    provider = _RecordingProvider(_respond)
    monkeypatch.setattr(provider_module, "get_provider", lambda *args, **kwargs: provider)

    await _update_summary(session.id, db)
    await db.refresh(session)

    metadata = dict(session.metadata_ or {})
    assert provider.calls == 1
    assert metadata["summary_references"] == [valid_ref]
    evidence_map = metadata["summary_evidence_map"]
    assert isinstance(evidence_map, list) and evidence_map
    assert all(set(item) == {"ref", "role", "tool_name", "excerpt"} for item in evidence_map)
    assert metadata["summary_source_last_message_id"] == messages[-9].id  # last message outside the window
    # hallucinated marker was dropped from stored references and text
    assert "[msg:hallucinated]" not in json.dumps(metadata["summary_json"])
    assert valid_ref in metadata["summary_json"]["findings"][0]["text"]
    # the structured summary and its text form are both stored
    assert isinstance(metadata.get("summary_json"), dict)
    assert "Goal:" in metadata["summary"]


@pytest.mark.asyncio
async def test_update_summary_cooldown_skips_same_source_last_message(db, monkeypatch):
    from app.agent import providers as provider_module

    session, _ = await _seed_session(db)
    provider = _RecordingProvider(lambda _prompt: json.dumps({"goal": "g", "state": "in_progress"}))
    monkeypatch.setattr(provider_module, "get_provider", lambda *args, **kwargs: provider)

    await _update_summary(session.id, db)
    assert provider.calls == 1
    await db.refresh(session)

    # Force past the message-count skip so only the cooldown can stop the rerun.
    metadata = dict(session.metadata_ or {})
    metadata["summary_message_count"] = 0
    session.metadata_ = metadata
    await db.commit()

    await _update_summary(session.id, db)
    assert provider.calls == 1  # cooldown skipped the second run


@pytest.mark.asyncio
async def test_get_session_summary_evidence_returns_message_content(db):
    session, messages = await _seed_session(db)
    tool = GetSessionSummaryEvidenceTool()

    result = await tool.execute({"reference_id": f"msg:{messages[0].id}"}, _tool_context(db, session.id))

    assert result["found"] is True
    assert result["message_id"] == messages[0].id
    assert result["role"] == "user"
    assert "Message 0" in result["content"]


@pytest.mark.asyncio
async def test_get_session_summary_evidence_resolves_tool_call_reference(db):
    session, _ = await _seed_session(db)
    message = Message(
        id=str(uuid.uuid4()),
        session_id=session.id,
        role="assistant",
        content="",
        tool_calls=[{"id": "tc-99", "function": {"name": "get_pod_logs", "arguments": "{}"}}],
    )
    db.add(message)
    await db.commit()

    result = await GetSessionSummaryEvidenceTool().execute(
        {"reference_id": "tool_call:tc-99", "detail_level": "full"}, _tool_context(db, session.id)
    )

    assert result["found"] is True
    assert result["message_id"] == message.id
    assert result["tool_name"] == "get_pod_logs"
    assert result["tool_item"]["id"] == "tc-99"


@pytest.mark.asyncio
async def test_get_session_summary_evidence_not_found_and_bad_reference(db):
    session, _ = await _seed_session(db, message_count=2)
    tool = GetSessionSummaryEvidenceTool()
    context = _tool_context(db, session.id)

    missing = await tool.execute({"reference_id": f"msg:{uuid.uuid4()}"}, context)
    assert missing["found"] is False
    assert missing["error"] == "Reference not found in this session"

    malformed = await tool.execute({"reference_id": "artifact:xyz"}, context)
    assert malformed["found"] is False
    assert "reference_id must look like" in malformed["error"]


@pytest.mark.asyncio
async def test_get_session_summary_evidence_denies_cross_session_reads(db):
    session_a, _ = await _seed_session(db, message_count=2)
    session_b, messages_b = await _seed_session(db, message_count=2)
    del session_b

    result = await GetSessionSummaryEvidenceTool().execute(
        {"reference_id": f"msg:{messages_b[0].id}"}, _tool_context(db, session_a.id)
    )

    assert result["found"] is False
    assert result["error"] == "Reference not found in this session"
