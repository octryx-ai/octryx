"""Board notifications are deduplicated and resolved (none when in-app notifications are off), redacting a decided request blanks its decision everywhere, and a missing workspace is 404 for everyone."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.models import AgentBoardMessage, AuditLog, Notification
from app.models.worker.teaming import NotificationPreference
from app.services.mcp_agent_board_tools import board_tool_handlers
from tests.agent_board.board_rest_support import _decide, _get, _post, team  # noqa: F401
from tests.agent_board.support import scope_for, seed_item


async def _notifications(db, user_id):
    rows = (await db.execute(select(Notification).where(Notification.user_id == user_id,
                                                        Notification.type.like("agent_board.%")))).scalars().all()
    for row in rows:
        await db.refresh(row)
    return rows


@pytest.mark.asyncio
async def test_notifications_are_deduplicated_and_resolved(client, db, team):  # noqa: F811
    item = await seed_item(db, team.ws, "BRD-6")
    request = await team.post(db, kind="decision_request", body="Secret plan text", to_user_id=team.ben,
                              work_item_id=item.id, options=["yes"])
    await _get(client, "/action-needed", team.ben)
    await _get(client, "/action-needed", team.ben)

    [created] = await _notifications(db, team.ben)
    assert created.type == "agent_board.decision_request" and created.is_read is False
    assert request["id"] in created.link and created.body is None and "Secret plan" not in created.title
    assert created.title.startswith("Decision needed – BRD-6")

    assert (await _decide(client, request["id"], team.ben, option="yes")).status_code == 200
    [resolved] = await _notifications(db, team.ben)
    assert resolved.is_read is True and resolved.read_at is not None
    assert (await _get(client, "/action-needed", team.ben)).json()["count"] == 0  # answered: no longer needed
    await _get(client, "/action-needed", team.ben)
    assert len(await _notifications(db, team.ben)) == 1

    # Cleared without an answer (redacted): the next poll resolves it.
    other = await team.post(db, kind="decision_request", body="Deploy?", to_user_id=team.ben)
    await _get(client, "/action-needed", team.ben)
    row = await db.get(AgentBoardMessage, other["id"])
    row.redacted_at = row.created_at
    await db.commit()
    await _get(client, "/action-needed", team.ben)
    assert all(entry.is_read for entry in await _notifications(db, team.ben))


@pytest.mark.asyncio
async def test_no_notification_when_in_app_notifications_are_off(client, db, team):  # noqa: F811
    db.add(NotificationPreference(user_id=team.ben, in_app_enabled=False))
    await db.commit()
    await team.post(db, kind="decision_request", body="Merge?", to_user_id=team.ben)
    answer = (await _get(client, "/action-needed", team.ben)).json()
    assert answer["count"] == 1 and await _notifications(db, team.ben) == []


@pytest.mark.asyncio
async def test_redacting_a_decided_request_blanks_its_decision_everywhere(client, db, team):  # noqa: F811
    """The chosen option and text never outlive the redaction of their request."""
    request = await team.post(db, kind="decision_request", body="Pick one", options=["alpha-sensitive", "beta"],
                              to_user_id=team.ben)
    decided = await _decide(client, request["id"], team.ben, option="alpha-sensitive", text="text-sensitive")
    redacted = await _post(client, f"/messages/{request['id']}/redact", team.owner)

    listed = (await _get(client, "/messages", team.owner, project_id=team.ws)).json()
    thread = (await _get(client, f"/messages/{request['id']}/thread", team.owner)).json()
    user, scope = await scope_for(db, team.anna)
    mcp = await board_tool_handlers({"x-octryx-session": team.anna_key})["board_read"](
        db, user=user, scope=scope, arguments={})
    dump = str([listed, thread, mcp, redacted.json()])

    assert decided.status_code == 200 and redacted.status_code == 200
    assert "alpha-sensitive" not in dump and "text-sensitive" not in dump
    root = next(entry for entry in listed["items"] if entry["id"] == request["id"])
    assert root["decided"]["option"] is None and root["decided"]["text"] is None
    assert root["decided"]["by"]["id"] == team.ben and root["decided"]["at"] is not None
    assert thread["root"]["decided"] == root["decided"]
    decision = await db.get(AgentBoardMessage, decided.json()["decision"]["id"])
    await db.refresh(decision)
    assert (decision.body, decision.options) == ("", [])
    audit = (await db.execute(select(AuditLog).where(AuditLog.action == "agent_board.message.redacted"))).scalar_one()
    assert audit.details["cascaded_decision_id"] == decision.id


@pytest.mark.asyncio
async def test_a_redacted_undecided_request_keeps_no_cascade(client, db, team):  # noqa: F811
    request = await team.post(db, kind="decision_request", body="Pick", options=["a"], to_user_id=team.ben)
    other = await team.post(db, kind="decision_request", body="Other", options=["keep-me"], to_user_id=team.ben)
    await _decide(client, other["id"], team.ben, option="keep-me")
    await _post(client, f"/messages/{request['id']}/redact", team.owner)
    listed = (await _get(client, "/messages", team.owner, project_id=team.ws)).json()["items"]
    untouched = next(entry for entry in listed if entry["id"] == other["id"])
    assert untouched["decided"]["option"] == "keep-me"
    audit = (await db.execute(select(AuditLog).where(AuditLog.action == "agent_board.message.redacted"))).scalar_one()
    assert "cascaded_decision_id" not in audit.details


@pytest.mark.asyncio
async def test_a_missing_workspace_is_404_for_everyone_including_platform_admins(client, db, team):  # noqa: F811
    """Never a 500 and never a 200 for an id that names no Workspace."""
    item = await seed_item(db, team.ws, "BRD-1")
    await db.commit()
    for user_id in (team.platform_admin, team.owner):
        assert (await _get(client, "/claims", user_id, project_id="nonexistent")).status_code == 404
        assert (await _get(client, "/messages", user_id, project_id="nonexistent")).status_code == 404
        handoff = await _post(client, "/handoff-requests", user_id, {
            "project_id": "nonexistent", "work_item_id": item.id, "to_user_id": team.ben, "body": "x"})
        assert handoff.status_code == 404
    assert (await _get(client, "/claims", team.platform_admin, project_id=team.ws)).status_code == 200


@pytest.mark.asyncio
async def test_a_request_redacted_before_the_cascade_still_hides_its_decision(client, db, team):  # noqa: F811
    """A redacted row that keeps its decision's option: the envelope hides it regardless."""
    request = await team.post(db, kind="decision_request", body="Pick", options=["legacy-option"], to_user_id=team.ben)
    await _decide(client, request["id"], team.ben, option="legacy-option", text="legacy-text")
    row = await db.get(AgentBoardMessage, request["id"])
    row.body, row.options, row.redacted_at = "", [], row.created_at  # an old redaction, no cascade
    await db.commit()
    root = (await _get(client, f"/messages/{request['id']}/thread", team.owner)).json()["root"]
    assert (root["decided"]["option"], root["decided"]["text"]) == (None, None)
    assert root["decided"]["by"]["id"] == team.ben
