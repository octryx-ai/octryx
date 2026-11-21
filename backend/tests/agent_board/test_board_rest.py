"""Board REST, decision permissions, handoffs, redaction, action-needed."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.models import AgentBoardMessage, AgentPresence, AuditLog
from app.services.agent_board import messages as messages_module
from app.services.agent_gateway.presence import session_key_hash
from app.services.mcp_agent_board_tools import board_tool_handlers
from tests.agent_board.board_rest_support import _decide, _get, _post, team  # noqa: F401
from tests.agent_board.support import agent, scope_for, seed_item
from tests.agent_board.work_item_claims_support import _claim

AWS_KEY = "AKIA" + "ABCDEFGHIJKLMNOP"


@pytest.mark.asyncio
async def test_messages_are_listed_newest_first_with_acks_viewer_and_filters(client, db, team):  # noqa: F811
    item = await seed_item(db, team.ws, "BRD-6")
    first = await team.post(db, kind="question", body="first", to_user_id=team.ben, work_item_id=item.id)
    second = await team.post(db, kind="info", body="<b>second</b>")
    await _post(client, "/messages", team.ben)  # wrong method: nothing happens
    user, scope = await scope_for(db, team.ben, grant_id="grant-b")
    await board_tool_handlers({})["board_ack"](db, user=user, scope=scope, arguments={"message_ids": [first["id"]]})
    await db.commit()

    listed = await _get(client, "/messages", team.ben, project_id=team.ws)
    paged = await _get(client, "/messages", team.ben, project_id=team.ws, limit=1)
    older = await _get(client, "/messages", team.ben, project_id=team.ws, limit=1, cursor=paged.json()["next_cursor"])
    by_item = await _get(client, "/messages", team.ben, project_id=team.ws, work_item_id=item.id)
    by_kind = await _get(client, "/messages", team.ben, project_id=team.ws, kind="info")
    by_agent = await _get(client, "/messages", team.ben, project_id=team.ws, agent_hash=session_key_hash(team.anna_key))
    by_other_agent = await _get(client, "/messages", team.ben, project_id=team.ws, agent_hash="0" * 24)
    hidden = await _get(client, "/messages", team.outsider, project_id=team.ws)
    as_owner = await _get(client, "/messages", team.owner, project_id=team.ws)

    body = listed.json()
    assert [entry["id"] for entry in body["items"]] == [second["id"], first["id"]]
    assert body["items"][0]["body"] == "<b>second</b>"  # stored and returned as plain data
    assert body["viewer"] == {"user_id": team.ben, "can_admin": False}
    assert as_owner.json()["viewer"] == {"user_id": team.owner, "can_admin": True}
    ack = body["items"][1]["acks"][0]
    assert ack["recipient"] == {"kind": "agent", "user": body["items"][1]["to"]["user"],
                                "agent_hash": ack["recipient"]["agent_hash"]} and ack["acked_at"].endswith("Z")
    assert body["items"][1]["to"]["user"]["id"] == team.ben
    assert [e["id"] for e in older.json()["items"]] == [first["id"]] and older.json()["next_cursor"] is None
    assert [e["id"] for e in by_item.json()["items"]] == [first["id"]]
    assert [e["id"] for e in by_kind.json()["items"]] == [second["id"]]
    assert len(by_agent.json()["items"]) == 2 and by_other_agent.json()["items"] == []
    assert hidden.status_code == 404


@pytest.mark.asyncio
async def test_a_thread_has_its_root_and_replies_and_hides_from_outsiders(client, db, team):  # noqa: F811
    root = await team.post(db, kind="question", body="root")
    reply = await team.post(db, kind="answer", body="reply", reply_to=root["id"])
    nested = await team.post(db, kind="info", body="nested", reply_to=reply["id"])

    from_reply = (await _get(client, f"/messages/{reply['id']}/thread", team.ben)).json()
    hidden = await _get(client, f"/messages/{root['id']}/thread", team.outsider)
    missing = await _get(client, "/messages/nope/thread", team.ben)

    assert from_reply["root"]["id"] == root["id"]
    assert [entry["id"] for entry in from_reply["replies"]] == [reply["id"], nested["id"]]
    assert (hidden.status_code, missing.status_code) == (404, 404)


@pytest.mark.asyncio
async def test_decision_permissions_follow_the_addressee(client, db, team):  # noqa: F811
    to_ben = await team.post(db, kind="decision_request", body="Merge?", to_user_id=team.ben, options=["yes", "no"])
    to_admins = await team.post(db, kind="decision_request", body="Deploy?", to_role="admins", options=["go"])
    to_nobody = await team.post(db, kind="decision_request", body="Rename?")
    to_agent = await team.post(db, kind="decision_request", body="Agent?", to_agent_hash="a" * 24)

    assert (await _decide(client, to_ben["id"], team.owner, option="yes")).status_code == 403
    assert (await _decide(client, to_ben["id"], team.outsider, option="yes")).status_code == 404
    assert (await _decide(client, to_ben["id"], team.ben, option="maybe")).status_code == 422
    assert (await _decide(client, to_ben["id"], team.ben)).status_code == 422
    secret = await _decide(client, to_ben["id"], team.ben, text=f"key {AWS_KEY}")
    assert secret.status_code == 422 and AWS_KEY not in secret.text
    decided = await _decide(client, to_ben["id"], team.ben, option="yes", text="ship it")
    twice = await _decide(client, to_ben["id"], team.ben, option="no")
    assert decided.status_code == 200 and twice.status_code == 409
    assert twice.json()["detail"] == {"code": "already_decided"}

    assert (await _decide(client, to_admins["id"], team.ben, option="go")).status_code == 403
    assert (await _decide(client, to_admins["id"], team.admin, option="go")).status_code == 200
    assert (await _decide(client, to_nobody["id"], team.anna, text="x")).status_code == 403
    assert (await _decide(client, to_nobody["id"], team.owner, text="Yes, rename")).status_code == 200
    assert (await _decide(client, to_agent["id"], team.owner, text="x")).status_code == 403
    assert (await _decide(client, to_agent["id"], team.platform_admin, text="override")).status_code == 200
    info = await team.post(db, kind="info", body="not a request")
    assert (await _decide(client, info["id"], team.owner, text="x")).json()["detail"] == {
        "code": "not_a_decision_request"}

    decision = decided.json()["decision"]
    assert decision["kind"] == "decision" and decision["author"] == {
        "type": "human", "user": decision["author"]["user"], "agent_hash": None}
    assert decision["author"]["user"]["id"] == team.ben and decision["reply_to"] == to_ben["id"]
    assert decision["to"]["agent_hash"] == session_key_hash(team.anna_key)
    request = (await _get(client, f"/messages/{to_ben['id']}/thread", team.anna)).json()["root"]
    assert request["decided"] == {"by": decision["author"]["user"], "at": decision["created_at"], "option": "yes",
                                  "text": "ship it"}
    user, scope = await scope_for(db, team.anna)
    inbox = await board_tool_handlers({"x-octryx-session": team.anna_key})["board_read"](
        db, user=user, scope=scope, arguments={"addressed_to_me": True})
    assert [entry["kind"] for entry in inbox["items"]] == ["decision"] * 4  # every decision goes back to the asker


@pytest.mark.asyncio
async def test_a_decision_race_has_one_winner(client, db, team, monkeypatch):  # noqa: F811
    request = await team.post(db, kind="decision_request", body="Merge?", to_user_id=team.ben, options=["yes"])
    assert (await _decide(client, request["id"], team.ben, option="yes")).status_code == 200

    async def not_seen(session, request_id):
        return None

    monkeypatch.setattr(messages_module, "existing_decision", not_seen)
    raced = await _decide(client, request["id"], team.platform_admin, option="yes")
    assert raced.status_code == 409 and raced.json()["detail"] == {"code": "already_decided"}
    decisions = (await db.execute(select(AgentBoardMessage).where(AgentBoardMessage.kind == "decision"))).scalars()
    assert len(decisions.all()) == 1


@pytest.mark.asyncio
async def test_handoff_requests_and_redaction_are_for_admins(client, db, team):  # noqa: F811
    item = await seed_item(db, team.ws, "BRD-9")
    await db.commit()
    body = {"project_id": team.ws, "work_item_id": item.id, "to_user_id": team.ben, "body": "Please take over"}

    by_member = await _post(client, "/handoff-requests", team.anna, body)
    by_outsider = await _post(client, "/handoff-requests", team.outsider, body)
    secret = await _post(client, "/handoff-requests", team.owner, {**body, "body": f"token {AWS_KEY}"})
    stranger = await _post(client, "/handoff-requests", team.owner, {**body, "to_user_id": team.outsider})
    created = await _post(client, "/handoff-requests", team.owner, body)

    assert by_member.status_code == 403  # a member without the admin role
    # An outsider learns nothing: a foreign Workspace answers exactly like an unknown one.
    unknown = await _post(client, "/handoff-requests", team.outsider, {**body, "project_id": str(uuid.uuid4())})
    assert by_outsider.status_code == unknown.status_code == 404
    assert by_outsider.json()["detail"] == unknown.json()["detail"]
    assert by_outsider.json()["detail"]["code"] == "project_not_found"
    assert secret.status_code == 422 and AWS_KEY not in secret.text
    assert stranger.status_code == 422
    message = created.json()["message"]
    assert (message["kind"], message["author"]["type"], message["to"]["user"]["id"]) == (
        "handoff_request", "human", team.ben)
    assert message["author"]["user"]["id"] == team.owner and message["on_behalf_of"] is None

    question = await team.post(db, kind="decision_request", body="secret-ish plan", options=["a"])
    assert (await _post(client, f"/messages/{question['id']}/redact", team.anna)).status_code == 403
    # A foreign item answers exactly like an item that does not exist.
    hidden_item = await _post(client, f"/messages/{question['id']}/redact", team.outsider)
    missing_item = await _post(client, f"/messages/{uuid.uuid4()}/redact", team.outsider)
    assert hidden_item.status_code == missing_item.status_code == 404
    assert hidden_item.json()["detail"] == missing_item.json()["detail"]
    redacted = (await _post(client, f"/messages/{question['id']}/redact", team.admin)).json()["message"]
    assert (redacted["body"], redacted["options"], redacted["id"]) == ("", [], question["id"])
    assert redacted["redacted_at"] is not None
    row = await db.get(AgentBoardMessage, question["id"])
    await db.refresh(row)
    assert row.redacted_by == team.admin and row.body == ""
    audit = (await db.execute(select(AuditLog).where(AuditLog.action == "agent_board.message.redacted"))).scalar_one()
    assert audit.resource_id == question["id"] and "secret-ish" not in str(audit.details)
    assert (await _decide(client, question["id"], team.owner, option="a")).status_code == 409


@pytest.mark.asyncio
async def test_action_needed_follows_the_role(client, db, team):  # noqa: F811
    item = await seed_item(db, team.ws, "BRD-6")
    to_ben = await team.post(db, kind="decision_request", body="Merge?", to_user_id=team.ben, work_item_id=item.id)
    to_admins = await team.post(db, kind="decision_request", body="Deploy?", to_role="admins")
    to_nobody = await team.post(db, kind="decision_request", body="Rename?")
    await team.post(db, kind="question", body="not a decision", to_user_id=team.ben)

    async def kinds(user_id):
        answer = (await _get(client, "/action-needed", user_id)).json()
        assert answer["count"] == len(answer["items"])
        return {(entry["kind"], entry.get("message_id") or entry.get("claim_id")) for entry in answer["items"]}, answer

    ben, ben_answer = await kinds(team.ben)
    owner, _ = await kinds(team.owner)
    anna, _ = await kinds(team.anna)
    outsider, _ = await kinds(team.outsider)

    assert ben == {("decision_request", to_ben["id"])}
    assert owner == {("decision_request", to_admins["id"]), ("decision_request", to_nobody["id"])}
    assert anna == set() and outsider == set()
    entry = ben_answer["items"][0]
    assert entry["project"] == {"id": team.ws, "name": entry["project"]["name"]}
    assert entry["work_item"]["key"] == "BRD-6" and entry["agent"]["agent_hash"] == session_key_hash(team.anna_key)
    assert entry["agent"]["user"]["id"] == team.anna and ben_answer["viewer"] == {"user_id": team.ben,
                                                                                  "can_admin": False}

    # A seat session at its limit that still holds a claim: admins only.
    presence = (await db.execute(select(AgentPresence).where(AgentPresence.session_key == team.anna_key))).scalar_one()
    claim = await _claim(db, await agent(db, team.anna, session_key=team.anna_key), item)
    presence.state = "limit_reached"
    await db.commit()
    owner_after, _ = await kinds(team.owner)
    ben_after, _ = await kinds(team.ben)
    assert ("limit_reached_with_claim", claim["claim_id"]) in owner_after
    assert ("limit_reached_with_claim", claim["claim_id"]) not in ben_after
