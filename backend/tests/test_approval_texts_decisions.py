"""Approval texts: Decisions, details without the subtitle, plan writes, all worded by one formatter."""

from __future__ import annotations

import json
import uuid
from types import SimpleNamespace

import pytest

from app.agent.runtime.trace_runtime import persist_turn_trace
from app.models import ChangePreview
from app.services.approval.decision_texts import decision_rule_text
from app.services.approval.presentation import approval_texts, readable_plan
from app.services.change_preview.service import serialize_change_preview
from app.services.decisions.timeline import get_decision, list_decisions
from app.services.decisions.tool_dispatch import record_tool_dispatch
from app.services.policy_engine.decision_log import clear_decision_buffer, flush_decision_log
from app.services.trace_gate_outcome import gate_outcome_marker
from app.tools import write_plan_tool
from tests.chat_write_plan_support import chat, writes  # noqa: F401 - fixtures
from tests.observability_support import admin_user, call_as, session_for, workspace
from tests.services.governance.test_approvals_409_texts_push import SERVER_TITLE, TOOL_RULE, _pending, _team_workspace
from tests.services.runtime.test_chat_write_plan import EPIC, _propose

NOT_SET_UP = "The execution check stopped the turn because something it needs is not set up"


@pytest.fixture(autouse=True)
def _clean_buffer():
    clear_decision_buffer()
    yield
    clear_decision_buffer()


@pytest.mark.asyncio
async def test_decisions_show_an_approval_like_its_card_and_keep_the_codes(client, db):
    project, owner, _member = await _team_workspace(db)
    blocked = await _pending(db, project, owner)

    response = await call_as(client, "GET", f"/api/v1/observability/decisions?approval_id={blocked['approval_id']}",
                             await admin_user(db))
    [requested] = response.json()["items"]
    assert (requested["what"], requested["subtitle"], requested["rule"]) == (SERVER_TITLE, TOOL_RULE, TOOL_RULE)
    assert requested["what_code"] == "Approve tool execution for run_cli_command"
    assert requested["rule_code"] == "require_for_tools"
    detail = await get_decision(db, requested["id"])
    assert detail["what"] == SERVER_TITLE and detail["lifecycle"][0]["what"] == SERVER_TITLE


@pytest.mark.asyncio
async def test_a_stopped_turn_and_a_refused_tool_read_in_words_with_their_codes(db):
    admin = await admin_user(db)
    project = await workspace(db)
    session = await session_for(db, admin, project=project)
    await persist_turn_trace(
        db=db, session_id=session.id, message_id=None, provider="execution-gate", model="", input_messages=[],
        context_snapshot={"request_id": "req-texts"}, tool_trace=[], usage={},
        raw_output=gate_outcome_marker(gate="execution_gate", label="execution gate", status="needs_configuration",
                                       reason="No model is configured."),
    )
    context = SimpleNamespace(user_id=admin.id, project_ids=[project.id], session_id=session.id, request_id="req-t")
    record_tool_dispatch("run_cli_command", context, {"tool_execution": {"category": "denied_by_policy",
                                                                         "policy": "project_tool_policy"}})
    await flush_decision_log(db, prune=False)
    await db.commit()

    by_gate = {item["gate"]: item for item in (await list_decisions(db, workspace_id=project.id))["items"]}
    gate, tool = by_gate["execution_gate"], by_gate["tool_policy"]
    assert (gate["rule"], gate["rule_code"]) == (NOT_SET_UP, "execution_gate: needs_configuration")
    assert (tool["what"], tool["what_code"]) == (SERVER_TITLE, "Tool run_cli_command")
    assert (tool["rule"], tool["rule_code"]) == ("The Workspace's tool policy does not allow this tool",
                                                 "project_tool_policy")


@pytest.mark.parametrize(("code", "text"), [
    ("runtime_readiness: needs_configuration",
     "The runtime readiness check stopped the turn because something it needs is not set up"),
    ("execution_gate: needs_clarification", "The execution check stopped the turn until the request is clarified"),
    ("mcp_access_policy", "The MCP access policy does not allow this server or tool"),
    ("require_for_tools", TOOL_RULE),
    # Written in words already, or unknown: served as stored, never guessed.
    ("approval rule: Four-eyes · self-approval", "approval rule: Four-eyes · self-approval"),
    ("cedar-policy-7", "cedar-policy-7"),
])
def test_decision_rules_in_words(code, text):
    assert decision_rule_text(code) == text


@pytest.mark.asyncio
async def test_a_new_gate_preview_does_not_repeat_its_subtitle_in_the_details(db):
    project, owner, _member = await _team_workspace(db)
    blocked = await _pending(db, project, owner)
    stored = json.loads((await db.get(ChangePreview, blocked["change_preview_id"])).preview_json)
    assert stored["subtitle"] == TOOL_RULE and TOOL_RULE not in stored["details"]
    assert approval_texts(stored)["details"] == ["It changes data"]


def test_a_preview_drops_the_subtitle_line_and_the_sentence_inside_a_line():
    stored = {"title": SERVER_TITLE, "subtitle": TOOL_RULE, "toolName": "run_cli_command",
              "details": [TOOL_RULE, f"{TOOL_RULE}. It changes data.", "command: npm test"]}
    assert approval_texts(stored)["details"] == ["It changes data", "command: npm test"]


@pytest.mark.asyncio
async def test_a_new_plan_titles_each_write_in_words(db, chat, writes, monkeypatch):  # noqa: F811
    _user, _session, context = chat

    async def untitled_own_preview(tool_name, params, routed_context):
        return {}

    monkeypatch.setattr("app.services.tool_approval.previews._routed_tool_preview", untitled_own_preview)
    held = await _propose(context, ("create_jira_ticket", EPIC),
                          ("add_jira_comment", {"ticket_id": "CHEF-1", "comment": "Plan confirmed"}))
    preview = json.loads((await db.get(ChangePreview, held["change_preview_id"])).preview_json)
    assert [write["title"] for write in preview["writes"]] == ["Create a Jira issue", "Comment on a Jira issue"]
    assert [write["tool"] for write in preview["writes"]] == ["create_jira_ticket", "add_jira_comment"]
    assert not any(line.startswith("write 1: create_jira_ticket") for line in preview["details"])
    entry = await write_plan_tool._write_preview({"tool": "add_jira_comment", "fields": {"ticket_id": "CHEF-1"},
                                                  "why": ""}, 0, "", context)
    assert entry["title"] == "Comment on a Jira issue"


def test_a_stored_plan_is_served_with_readable_write_titles():
    old_plan = {"kind": "write_plan", "title": "Write plan with 2 writes", "toolName": "propose_write_plan",
                "writes": [{"index": 0, "tool": "create_jira_ticket", "title": ""},
                           {"index": 1, "tool": "add_jira_comment", "title": None},
                           {"index": 2, "tool": "create_jira_ticket", "title": "Create Jira Epic Kitchen helper v1"}],
                "details": ["request: Kitchen helper", "write 1: create_jira_ticket via Jira",
                            "  summary: Kitchen helper v1", "write 2: add_jira_comment", "write 3: Create Jira Epic Kitchen helper v1"]}
    row = ChangePreview(id=str(uuid.uuid4()), tool_name="propose_write_plan", preview_json=json.dumps(old_plan),
                        request_fingerprint="fp")
    served = serialize_change_preview(row)["preview"]
    assert [write["title"] for write in served["writes"]] == [
        "Create a Jira issue", "Comment on a Jira issue", "Create Jira Epic Kitchen helper v1"]
    assert served["details"] == ["request: Kitchen helper", "write 1: Create a Jira issue via Jira", "  summary: Kitchen helper v1",
                                 "write 2: Comment on a Jira issue", "write 3: Create Jira Epic Kitchen helper v1"]
    assert approval_texts(old_plan)["details"] == served["details"]
    assert readable_plan({"kind": "tool_execution", "title": "x"}) == {"kind": "tool_execution", "title": "x"}


def test_policy_sentences_name_what_is_missing():
    from app.services.approval.decision_texts import decision_rule_text

    assert "verification checks must pass" in decision_rule_text("coding_delivery_gate")
    assert decision_rule_text("tool_governance_metadata").endswith("blocked until an admin describes it")
