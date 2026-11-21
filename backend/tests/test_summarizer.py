import json
import uuid

import pytest
from sqlalchemy import select

from app.agent.core.runtime.summarizer import (
    _update_summary,
    build_history_messages,
)
from app.agent.core.runtime.summary_structure import parse_existing_summary_json, parse_summary_response
from app.models import Message, Session, User


class _FakeProvider:
    async def chat(self, *, messages, model, temperature, max_tokens):
        del model, temperature, max_tokens
        assert messages[0]["role"] == "system"
        return {
            "content": json.dumps(
                {
                    "goal": "Analyse OOM crash for payment-service",
                    "findings": [
                        {
                            "type": "root_cause",
                            "text": "payment-service hit OOMKilled after rollout",
                            "entities": ["payment-service", "RIVER-42"],
                        }
                    ],
                    "actions_taken": [{"tool": "kubectl", "action": "get pod logs", "result": "OOMKilled x3"}],
                    "open_items": ["memory limit not yet updated"],
                    "state": "in_progress",
                }
            )
        }


@pytest.mark.asyncio
async def test_update_summary_persists_structured_summary_json(db, monkeypatch):
    from app.agent import providers as provider_module

    monkeypatch.setattr(provider_module, "get_provider", lambda *args, **kwargs: _FakeProvider())
    user = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    session = Session(id=str(uuid.uuid4()), user_id=user.id, agent_type="chat", status="active", metadata_={})
    db.add(session)
    for idx in range(12):
        db.add(
            Message(
                id=str(uuid.uuid4()),
                session_id=session.id,
                role="user" if idx % 2 == 0 else "assistant",
                content=f"Message {idx} about payment-service OOMKilled and ticket RIVER-42.",
            )
        )
    await db.commit()

    await _update_summary(session.id, db)
    await db.refresh(session)

    metadata = dict(session.metadata_ or {})
    assert isinstance(metadata.get("summary_json"), dict)
    assert metadata["summary_json"]["goal"] == "Analyse OOM crash for payment-service"
    assert metadata["summary_json"]["findings"][0]["type"] == "root_cause"
    assert "Goal:" in metadata["summary"]
    assert metadata["summary_message_count"] >= 1


def test_build_history_messages_injects_structured_json_summary():
    class _Msg:
        def __init__(self, role: str, content: str):
            self.role = role
            self.content = content
            self.tool_calls = None

    history = [_Msg("user", f"message {idx}") for idx in range(12)]
    summary_json = {
        "goal": "Analyse OOM crash for payment-service",
        "findings": [{"type": "root_cause", "text": "OOMKilled", "entities": ["payment-service"]}],
        "actions_taken": [{"tool": "kubectl", "action": "get logs", "result": "OOMKilled x3"}],
        "open_items": ["adjust memory limit"],
        "state": "in_progress",
    }

    context_msgs, recent = build_history_messages(history, summary_json, include_summary=True)
    assert len(context_msgs) == 2
    assert "<session_summary_json>" in context_msgs[0]["content"]
    assert '"goal": "Analyse OOM crash for payment-service"' in context_msgs[0]["content"]
    assert len(recent) == 8


def test_parse_existing_summary_json_ignores_non_json_payloads():
    assert parse_existing_summary_json("not-json") == {}
    assert parse_existing_summary_json(None) == {}


def test_parse_summary_response_handles_malformed_tool_calls():
    class _Msg:
        def __init__(self, role: str, content: str, tool_calls):
            self.role = role
            self.content = content
            self.tool_calls = tool_calls

    payload = parse_summary_response(
        "not-json",
        fallback_goal="Investigate failure",
        existing_summary_json={},
        new_messages=[_Msg("assistant", "updated deployment after checks", ["bad-tool-call-shape"])],
    )

    assert payload["goal"] == "Investigate failure"
    assert payload["actions_taken"][0]["tool"] == ""
