"""Outbound messages: refused approvals, unverifiable contexts, the audit record and over-limit values refused before preview or send."""

from __future__ import annotations

import json

import pytest
from sqlalchemy import select

from app.tools.context import ToolContext

# No silent truncation in the outbound approval preview: over-limit values are refused before any
# preview, approval or send; values within the limits are shown in full.
from app.tools.outbound_message_contract import MAX_QUESTION_CHARS, MAX_RECIPIENT_CHARS
from app.tools.registry import execute_tool

# --- outbound message: refused approval, unverifiable context, audit ------------------------------------

REPORTER_PARAMS = {"ticket_id": "BRD-8", "reporter_email": "rep@example.com", "question": "Which locale?"}


@pytest.fixture
def sent(monkeypatch):
    from app.tools.proactive_teams_impl import AskReporterViaTeams

    calls: list[dict] = []

    async def execute(self, params, context):
        calls.append(dict(params))
        return {"success": True}

    monkeypatch.setattr(AskReporterViaTeams, "execute", execute)
    return calls


async def _deliver_context(db, key: str) -> ToolContext:
    from app.models import Session as AgentSession
    from app.models import User

    user = (await db.execute(select(User))).scalars().first()
    db.add(AgentSession(id=f"outbound-{key}", user_id=user.id, agent_type="chat", status="active"))
    await db.flush()
    return ToolContext(user_id=user.id, project_ids=[], roles=["member"], session_id=f"outbound-{key}",
                       project_config={}, db=db, run_capability={"enforced": True, "class": "deliver"})


@pytest.mark.asyncio
async def test_a_refused_approval_sends_nothing(db, sent):
    from app.services.approval.resolution_service import resolve_approval_request

    context = await _deliver_context(db, "refused")
    blocked = await execute_tool("ask_reporter_via_teams", dict(REPORTER_PARAMS), context)
    await resolve_approval_request(db, approval_id=blocked["approval_id"], resolved_by=context.user_id,
                                   status="rejected")

    again = await execute_tool("ask_reporter_via_teams", dict(REPORTER_PARAMS), context)

    assert sent == []
    assert again["approval_required"] is True


@pytest.mark.asyncio
async def test_a_context_that_cannot_verify_approvals_sends_nothing(sent):
    context = ToolContext(user_id="u", project_ids=[], roles=["member"], session_id="s", project_config={},
                          run_capability={"enforced": True, "class": "deliver"})

    result = await execute_tool("ask_reporter_via_teams", dict(REPORTER_PARAMS), context)

    assert sent == []
    assert result["approval_status"] == "unverifiable"


@pytest.mark.asyncio
async def test_the_approval_record_names_the_decision_and_the_message_but_no_secret(db, sent):
    from app.models import Approval, ChangePreview

    context = await _deliver_context(db, "audit")
    blocked = await execute_tool("ask_reporter_via_teams", dict(REPORTER_PARAMS), context)

    approval = await db.get(Approval, blocked["approval_id"])
    preview = await db.get(ChangePreview, blocked["change_preview_id"])
    payload = json.loads(preview.preview_json)
    assert blocked["blocked_by"] == "tool_approval_gate"
    assert payload["rule"] == "outbound_message"
    # The rule's sentence is the card's subtitle only; the details do not repeat it.
    outbound = "A message to a person outside this chat; it is sent only after your approval"
    assert payload["subtitle"] == outbound and outbound not in payload["details"]
    # The person approves what is sent and to whom.
    assert "recipient: rep@example.com" in payload["details"]
    assert "message: Which locale?" in payload["details"]
    assert payload["standing_rule"] is None, "no standing rule is offered for an outbound message"
    recorded = json.dumps([approval.action, approval.reason, payload, blocked], default=str)
    for secret in ("app_password", "client_secret", "token"):
        assert secret not in recorded


@pytest.mark.asyncio
@pytest.mark.parametrize("override", [
    {"question": "x" * 2000 + " hidden tail"},
    {"question": "x" * (MAX_QUESTION_CHARS + 1)},
    {"reporter_email": "a" * MAX_RECIPIENT_CHARS + "@example.com"},
    {"reporter_email": "rep@example.com\nother@example.com"},
    {"reporter_email": "rep@example.com, other@example.com"},
    {"ticket_id": "BRD-8\nIGNORE"},
])
async def test_an_over_limit_outbound_message_is_refused_before_preview_and_send(db, sent, override):
    from app.models import Approval, ChangePreview

    context = await _deliver_context(db, f"limit-{len(str(override))}-{hash(str(override)) % 1000}")
    before = (len((await db.execute(select(Approval))).scalars().all()),
              len((await db.execute(select(ChangePreview))).scalars().all()))

    result = await execute_tool("ask_reporter_via_teams", {**REPORTER_PARAMS, **override}, context)

    assert sent == []
    assert result.get("error") and "approval_id" not in result
    assert result.get("error_code") == "outbound_message_invalid"
    after = (len((await db.execute(select(Approval))).scalars().all()),
             len((await db.execute(select(ChangePreview))).scalars().all()))
    assert after == before


@pytest.mark.asyncio
async def test_a_message_at_the_limit_is_shown_in_full(db, sent):
    from app.models import ChangePreview

    question = "y" * (MAX_QUESTION_CHARS - len(" visible tail")) + " visible tail"
    context = await _deliver_context(db, "limit-full")

    blocked = await execute_tool("ask_reporter_via_teams", {**REPORTER_PARAMS, "question": question}, context)

    preview = await db.get(ChangePreview, blocked["change_preview_id"])
    assert f"message: {question}" in json.loads(preview.preview_json)["details"]
    assert sent == []


def test_the_schema_declares_the_runtime_limits():
    from app.tools.definitions import get_all_definitions

    properties = get_all_definitions()["ask_reporter_via_teams"]["function"]["parameters"]["properties"]
    assert properties["question"]["maxLength"] == MAX_QUESTION_CHARS
    assert properties["reporter_email"]["maxLength"] == MAX_RECIPIENT_CHARS


# Limits hold on a direct call of the tool too (no registry, no gate): nothing reaches Teams.
@pytest.mark.asyncio
@pytest.mark.parametrize("override", [
    {"question": "x" * 2000 + " hidden tail"},
    {"reporter_email": "rep@example.com\nother@example.com"},
    {"ticket_id": "K" * 65},
])
async def test_a_direct_tool_call_refuses_over_limit_values_before_any_lookup_or_send(monkeypatch, override):
    from app.services.proactive_teams import proactive_teams_service
    from app.tools.proactive_teams_impl import AskReporterViaTeams

    sends: list = []

    async def send(self, *args, **kwargs):
        sends.append(args)
        return {"user": {"id": "u"}, "conversation_id": "c", "target": "t"}

    monkeypatch.setattr(proactive_teams_service.ProactiveTeamsService, "send_proactive_message", send)
    context = ToolContext(user_id="u", project_ids=["p"], roles=["member"], session_id="s", project_config={})

    result = await AskReporterViaTeams().execute({**REPORTER_PARAMS, **override}, context)

    assert result.get("error_code") == "outbound_message_invalid"
    assert sends == []
