"""Approvals: 409 when already decided, readable card texts, and a push for every approval the person may decide."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.models import Approval, ChangePreview, MobileDevice, MobilePushSubscription, Project, UserProject
from app.services.approval.presentation import approval_texts
from app.services.approval.tool_texts import rule_text, tool_title
from app.services.attention.service import attention
from app.services.change_preview.service import serialize_change_preview
from app.services.mobile import push
from app.services.mobile.webpush import SENT
from app.services.tool_approval.gate import enforce_tool_approval
from app.tools.context import ToolContext
from app.web._helpers.approval_serialization import _serialize_approval
from tests.mobile.mobile_pairing_support import _paired_phone
from tests.mobile.mobile_push_support import configured  # noqa: F401 - fixture
from tests.mobile.test_mobile_push import APPLE, _receiver
from tests.policy_engine_support import bearer
from tests.services.governance.test_standing_tool_approvals import _session, _user

POLICY = {"approval_policy": {"require_for_tools": ["run_cli_command"]}}
SERVER_TITLE = "Run a command on the Octryx server"
TOOL_RULE = "This tool needs approval in this Workspace"


async def _team_workspace(db) -> tuple[Project, object, object]:
    project = Project(id=str(uuid.uuid4()), name=f"ap-{uuid.uuid4().hex[:8]}", config=dict(POLICY),
                      is_active=True, access_mode="team")
    db.add(project)
    await db.flush()
    return project, await _user(db, "owner", project), await _user(db, "member", project)


async def _pending(db, project, owner) -> dict:
    session = await _session(db, project, owner)
    context = ToolContext(user_id=owner.id, project_ids=[project.id], roles=[], session_id=session.id,
                          project_config=dict(POLICY), db=db)
    blocked = await enforce_tool_approval("run_cli_command", {"command": "npm test"}, context)
    await db.commit()
    return blocked


async def _outsider(db):
    other = Project(id=str(uuid.uuid4()), name=f"x-{uuid.uuid4().hex[:8]}", config={}, is_active=True)
    db.add(other)
    await db.flush()
    return await _user(db, "member", other)


@pytest.mark.asyncio
async def test_a_second_decision_is_409_on_the_session_and_the_always_path(client, db):
    project, owner, _member = await _team_workspace(db)
    blocked = await _pending(db, project, owner)
    url = f"/api/v1/approvals/{blocked['approval_id']}"
    assert (await client.post(f"{url}/reject", json={}, headers=bearer(owner.id))).status_code == 200

    for path in ("approve", "reject", "always"):
        again = await client.post(f"{url}/{path}", json={}, headers=bearer(owner.id))
        assert again.status_code == 409, (path, again.text)
        assert again.json()["detail"] == {"code": "approval_already_resolved",
                                          "message": "This approval was already decided."}


@pytest.mark.asyncio
async def test_a_second_decision_is_409_on_the_sessionless_path(client, db):
    project, owner, _member = await _team_workspace(db)
    review = Approval(requested_by=owner.id, action="Publish routing policy", status="pending",
                      workspace_id=project.id)
    db.add(review)
    await db.commit()
    url = f"/api/v1/approvals/{review.id}/reject"
    assert (await client.post(url, json={}, headers=bearer(owner.id))).status_code == 200
    again = await client.post(url, json={}, headers=bearer(owner.id))
    assert again.status_code == 409 and again.json()["detail"]["code"] == "approval_already_resolved"


@pytest.mark.parametrize(("tool", "kwargs", "title"), [
    ("run_cli_command", {}, SERVER_TITLE),
    ("run_cli_command", {"on_device": True}, "Run a command on a device"),
    ("add_jira_comment", {}, "Comment on a Jira issue"),
    ("create_jira_ticket", {}, "Create a Jira issue"),
    ("transition_jira_ticket", {}, "Move a Jira issue to another status"),
    ("create_github_pull_request", {}, "Create a GitHub pull request"),
    ("mcp__tickets__close_case", {}, "Close case in tickets"),
    ("frobnicate_the_widget", {}, "Frobnicate the widget"),
    ("whatever", {"label": "MCP capability srv/run"}, "Use MCP capability srv/run"),
])
def test_tool_titles_say_what_runs_where(tool, kwargs, title):
    assert tool_title(tool, **kwargs) == title


@pytest.mark.parametrize(("rule", "kwargs", "text"), [
    ("require_for_tools", {}, TOOL_RULE),
    ("require_for_risks", {"risk": "write"}, "Writes need approval in this Workspace"),
    ("require_for_risks", {"risk": "admin"}, "Administrative actions need approval in this Workspace"),
    ("unattended_external_write", {"system": "Jira"},
     "No person started this run; its write to Jira needs your approval"),
    ("device_external_write", {"system": "Tickets"},
     "A device asks to write to Tickets through Octryx; it runs only after your approval"),
    ("chat_connector_write", {"system": "Jira"}, "A write to Jira from the chat; confirm exactly this call before it runs"),
    ("outbound_message", {}, "A message to a person outside this chat; it is sent only after your approval"),
    ("a_rule_from_tomorrow", {}, "This call needs approval"),
])
def test_rules_read_as_one_sentence_without_a_field_separator(rule, kwargs, text):
    assert rule_text(rule, **kwargs) == text and ": " not in text


def test_a_preview_without_a_title_reads_as_its_tool_and_rule():
    untitled = {"toolName": "add_jira_comment", "rule": "unattended_external_write", "risk": "write",
                "details": ["It changes data", "ticket: CHEF-1"]}
    assert approval_texts(untitled) == {
        "title": "Comment on a Jira issue",
        "subtitle": "No person started this run; its write to Jira needs your approval",
        "details": ["It changes data", "ticket: CHEF-1"],
    }
    assert approval_texts(None, "Approve tool execution for run_cli_command")["title"] == SERVER_TITLE


@pytest.mark.asyncio
async def test_the_gate_card_detail_and_decidable_list_carry_readable_texts_and_keep_the_codes(client, db):
    project, owner, _member = await _team_workspace(db)
    blocked = await _pending(db, project, owner)
    row = (await db.execute(select(ChangePreview).where(ChangePreview.id == blocked["change_preview_id"]))).scalar_one()
    stored = serialize_change_preview(row)
    payload = stored["preview"]
    assert (payload["title"], payload["subtitle"]) == (SERVER_TITLE, TOOL_RULE)
    assert payload["details"][:1] == ["It changes data"] and TOOL_RULE not in payload["details"]
    assert (payload["toolName"], payload["approvalSubject"], payload["rule"], payload["risk"]) == (
        "run_cli_command", "run_cli_command", "require_for_tools", "write")

    approval = await db.get(Approval, blocked["approval_id"])
    card = _serialize_approval(approval, change_preview=stored)
    assert (card["title"], card["subtitle"]) == (SERVER_TITLE, TOOL_RULE)
    detail = (await client.get(f"/api/v1/approvals/{approval.id}", headers=bearer(owner.id))).json()
    assert (detail["title"], detail["subtitle"], detail["details"][0]) == (SERVER_TITLE, TOOL_RULE, "It changes data")
    listed = (await client.get("/api/v1/approvals/decidable", headers=bearer(owner.id))).json()
    [item] = [entry for entry in listed["items"] if entry["id"] == approval.id]
    assert item["title"] == SERVER_TITLE and item["payload"]["toolName"] == "run_cli_command"


@pytest.mark.asyncio
async def test_the_queue_lists_a_colleagues_approval_for_a_decider_once_and_not_for_others(client, db):
    project, owner, member = await _team_workspace(db)
    blocked = await _pending(db, project, owner)
    key = f"tool_approval:{blocked['approval_id']}"

    for person, subtitle in ((owner, "Approval in your session"), (member, "Approval you may decide")):
        entries = [item for item in (await attention(db, person))["items"] if item["id"] == blocked["approval_id"]]
        assert [item["key"] for item in entries] == [key]
        assert (entries[0]["title"], entries[0]["subtitle"], entries[0]["severity"]) == (SERVER_TITLE, subtitle,
                                                                                         "action")
        assert entries[0]["workspace"]["id"] == project.id
        assert entries[0]["actions"][0]["request"]["path"] == f"/api/v1/approvals/{blocked['approval_id']}/approve"
    decidable = (await client.get("/api/v1/approvals/decidable", headers=bearer(member.id))).json()
    assert blocked["approval_id"] in {item["id"] for item in decidable["items"]}

    outsider = await _outsider(db)
    assert all(item["id"] != blocked["approval_id"] for item in (await attention(db, outsider))["items"])


@pytest.mark.asyncio
async def test_the_decider_s_phone_is_pushed_once_for_a_colleagues_approval(client, db, configured):  # noqa: F811
    project, owner, _member = await _team_workspace(db)
    decider, _mac, _claimed = await _paired_phone(client, db, username=f"decider-{uuid.uuid4().hex[:6]}")
    db.add(UserProject(user_id=decider.id, project_id=project.id, role="member", granted_by=owner.id))
    device = (await db.execute(select(MobileDevice).where(MobileDevice.owner_user_id == decider.id))).scalar_one()
    _key, p256dh, auth = _receiver()
    row = MobilePushSubscription(mobile_device_id=device.id, owner_user_id=decider.id, endpoint=APPLE,
                                 p256dh=p256dh, auth=auth, rules=push.DEFAULT_RULES, notified=None)
    db.add(row)
    await db.flush()
    sent: list[dict] = []

    async def sender(_http, _subscription, message, **_kwargs):
        sent.append(message)
        return SENT

    assert await push.sweep_subscription(db, row, http=None, sender=sender) == 0
    blocked = await _pending(db, project, owner)
    assert await push.sweep_subscription(db, row, http=None, sender=sender) == 1
    assert sent[0]["title"] == "Needs you" and sent[0]["body"] == f"{SERVER_TITLE} · {project.name}"
    assert sent[0]["url"] == f"/m/#item=tool_approval:{blocked['approval_id']}"
    assert await push.sweep_subscription(db, row, http=None, sender=sender) == 0 and len(sent) == 1
