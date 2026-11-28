"""Model-written secrets are stored and shown masked; the confirmed write still runs with the real value."""

from __future__ import annotations

import json

import pytest
from sqlalchemy import select

from app.models import Approval, ChangePreview, ToolCall
from app.models import Session as AgentSession
from app.services.secret_masking import SEALED_KEY, masked, real_fields, sealed_fields
from app.tools.registry import execute_tool
from tests.chat_write_plan_support import chat, writes  # noqa: F401 - fixtures
from tests.services.runtime.test_chat_write_plan import _confirm, _propose

TOKEN = "sk-proj-" + "a1b2c3d4e5f6g7h8i9j0k1l2m3n4"  # a fake key, built so no scanner sees a literal
COMMENT = {"ticket_id": "CHEF-1", "comment": f"Deploy with token {TOKEN}"}


def test_sealing_shows_masked_and_returns_the_real_fields():
    stored = sealed_fields(COMMENT)
    assert TOKEN not in json.dumps(stored) and stored["fields"]["ticket_id"] == "CHEF-1"
    assert real_fields(stored) == COMMENT
    assert sealed_fields({"ticket_id": "CHEF-1"}) == {"fields": {"ticket_id": "CHEF-1"}}
    assert masked({"api_key": "x1", "project_key": "CHEF"}) == {"api_key": "[redacted]", "project_key": "CHEF"}


@pytest.mark.asyncio
async def test_a_plan_with_a_secret_is_stored_masked_and_runs_with_the_real_value(db, chat, writes):  # noqa: F811
    user, session, context = chat

    held = await _propose(context, ("add_jira_comment", COMMENT), request="Comment the deploy token on CHEF-1")
    preview_json = (await db.execute(select(ChangePreview.preview_json).where(
        ChangePreview.id == held["change_preview_id"]))).scalar_one()
    assert TOKEN not in preview_json and "[redacted]" in preview_json
    assert all(TOKEN not in f"{row.action} {row.reason}" for row in (await db.execute(select(Approval))).scalars())
    await _confirm(db, user, held)
    await db.refresh(session)
    assert TOKEN not in json.dumps(session.metadata_, default=str)
    [entry] = [write for write in session.metadata_["chat_write_plan"]["writes"]]
    assert entry.get(SEALED_KEY)

    shown = entry["fields"]["comment"]
    result = await execute_tool("add_jira_comment", {"ticket_id": "CHEF-1", "comment": shown}, context)
    assert result == {"ok": True}
    assert writes == [("add_jira_comment", COMMENT)]


@pytest.mark.asyncio
async def test_tool_call_parameters_are_stored_masked(db, chat):  # noqa: F811
    _user, session, _context = chat
    row = ToolCall(session_id=session.id, tool_name="http_request",
                   parameters={"url": "https://api.example.test", "headers": {"Authorization": f"Bearer {TOKEN}"}})
    db.add(row)
    await db.flush()
    stored = (await db.execute(select(ToolCall.parameters).where(ToolCall.id == row.id))).scalar_one()
    assert TOKEN not in json.dumps(stored) and stored["url"] == "https://api.example.test"
    assert isinstance(session, AgentSession)


def test_a_secret_the_call_carried_never_comes_back_in_its_result():
    from app.services.secret_masking import mask_echoed_arguments

    arguments = {"body": {"note": f"deploy with token {TOKEN}", "api_key": "Zx9-very-secret", "title": "Hello"}}
    echoed = {"status": 201, "data": {"note": f"deploy with token {TOKEN}", "key": "Zx9-very-secret", "title": "Hello"}}
    clean = mask_echoed_arguments(echoed, arguments)
    assert TOKEN not in json.dumps(clean) and "Zx9-very-secret" not in json.dumps(clean)
    assert clean["data"]["title"] == "Hello" and clean["status"] == 201
    assert mask_echoed_arguments(echoed, {"title": "Hello"}) == echoed


@pytest.mark.asyncio
async def test_the_registry_returns_and_stores_a_result_without_the_calls_own_secret(db, chat, monkeypatch):  # noqa: F811
    from app.tools.registry import TOOL_REGISTRY

    _user, session, context = chat

    async def echo(params, context):
        return {"ok": True, "echo": params.get("comment")}

    monkeypatch.setattr(TOOL_REGISTRY["work_item_note"], "execute", echo)
    context.run_capability = {"class": "read_only", "enforced": True, "source": "flow_definition"}
    result = await execute_tool("work_item_note", {"item_id": "OCX-1", "comment": f"token {TOKEN}"}, context)
    assert result.get("ok") is True and "[redacted]" in result["echo"], result
    assert TOKEN not in json.dumps(result)
    row = ToolCall(session_id=session.id, tool_name="work_item_note", parameters={}, result={"echo": f"x {TOKEN}"})
    db.add(row)
    await db.flush()
    assert TOKEN not in json.dumps((await db.execute(select(ToolCall.result).where(ToolCall.id == row.id))).scalar_one())


def test_identifier_keys_stay_readable_while_credentials_are_masked():
    shown = masked({"details": ["project_key: CHEF", "issue_key: CHEF-1", f"api_key: {TOKEN}", f"STRIPE_KEY={TOKEN}"]})
    assert shown["details"][:2] == ["project_key: CHEF", "issue_key: CHEF-1"]
    assert TOKEN not in json.dumps(shown)
