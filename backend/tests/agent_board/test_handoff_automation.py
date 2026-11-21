"""Automatic handoff requests, available handoffs, action-needed, nudges, memory, test hook."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.models import AgentBoardMessage, AgentPresence, AuditLog, Notification, Project, User, WorkItem
from app.models.project.knowledge_memory import KnowledgeMemoryItem
from app.services.agent_board.automation import request_handoffs_for_presence
from app.services.agent_board.handoff_memory import capture_if_done, capture_latest_handoff_memory
from app.services.agent_board.session_hints import session_handoff_hints
from app.services.agent_gateway.allowance import Allowance
from app.services.agent_gateway.presence import record_allowance, session_key_hash
from app.time_utils import utc_now
from tests.agent_board.board_rest_support import _get, _post
from tests.agent_board.support import scope_for, seed_item
from tests.agent_board.test_handoffs import Pair
from tests.agent_board.test_takeover_rest import Board, _decide
from tests.agent_board.work_item_claims_support import _fenced

HOOK = "/api/v1/agent-board/test/presence-limit"


@pytest.fixture
async def board(db):
    return await Board().build(db)


async def _presence(db, session_key) -> AgentPresence:
    return (await db.execute(select(AgentPresence).where(AgentPresence.session_key == session_key))).scalar_one()


async def _auto_requests(db) -> list[AgentBoardMessage]:
    rows = await db.execute(select(AgentBoardMessage).where(AgentBoardMessage.author_type == "system"))
    return list(rows.scalars().all())


async def _hints(db, board, session_key):
    return await session_handoff_hints(db, session_key=session_key, agent_hash=session_key_hash(session_key),
                                       project_id=board.ws)


@pytest.mark.asyncio
async def test_an_allowance_near_the_limit_posts_one_automatic_request_per_claim(db, board):
    other = await seed_item(db, board.ws, "BRD-7")
    await db.commit()
    from tests.agent_board.support import agent
    from tests.agent_board.work_item_claims_support import _claim

    await _claim(db, await agent(db, board.anna, session_key=board.anna_key), other)
    await record_allowance(db, board.anna_key, Allowance(10.0, None, 85.0, None, None))
    assert await _auto_requests(db) == []  # 85 % is not near enough
    await record_allowance(db, board.anna_key, Allowance(10.0, None, 95.0, None, None))
    await record_allowance(db, board.anna_key, Allowance(10.0, None, 97.0, None, None))

    requests = await _auto_requests(db)
    assert len(requests) == 2 and {message.work_item_id for message in requests} == {board.item.id, other.id}
    message = next(message for message in requests if message.work_item_id == board.item.id)
    assert (message.kind, message.to_role, message.author_user_id, message.claim_id) == (
        "handoff_request", "admins", board.anna, board.claim["claim_id"])
    assert "BRD-6" in message.body and "95" not in message.body and "%" not in message.body
    # The partial unique index keeps it to one per claim even when the existence check is raced.
    duplicate = AgentBoardMessage(id=str(uuid.uuid4()), project_id=board.ws, author_type="system",
                                  author_user_id=board.anna, kind="handoff_request", body="x", options=[],
                                  created_at=utc_now(), claim_id=board.claim["claim_id"])
    with pytest.raises(IntegrityError):
        async with db.begin_nested():
            db.add(duplicate)
            await db.flush()


@pytest.mark.asyncio
async def test_limit_reached_also_requests_but_a_session_without_claims_does_not(db, board):
    ben = await _presence(db, board.ben_key)
    ben.state = "limit_reached"
    assert await request_handoffs_for_presence(db, ben, session_key_hash(board.ben_key)) == 0
    anna = await _presence(db, board.anna_key)
    anna.state = "limit_reached"
    assert await request_handoffs_for_presence(db, anna, session_key_hash(board.anna_key)) == 1
    from tests.agent_board.support import agent
    from tests.agent_board.work_item_claims_support import _claim

    fresh = await seed_item(db, board.ws, "BRD-9")
    await _claim(db, await agent(db, board.anna, session_key=board.anna_key), fresh)
    anna.stopped_at = utc_now()
    assert await request_handoffs_for_presence(db, anna, session_key_hash(board.anna_key)) == 0  # stopped: none


@pytest.mark.asyncio
async def test_available_handoffs_reach_members_with_spare_allowance_without_numbers(client, db, board):
    anna = await _presence(db, board.anna_key)
    anna.state = "limit_reached"
    await request_handoffs_for_presence(db, anna, session_key_hash(board.anna_key))
    await db.commit()

    async def kinds(user_id):
        answer = (await _get(client, "/action-needed", user_id)).json()
        return [entry for entry in answer["items"] if entry["kind"] == "available_handoff"]

    ben_items = await kinds(board.ben)
    assert [entry["work_item"]["key"] for entry in ben_items] == ["BRD-6"]
    entry = ben_items[0]
    assert set(entry) == {"kind", "project", "claim_id", "work_item", "agent", "created_at"}
    assert entry["agent"]["user"]["id"] == board.anna and "pct" not in str(entry)
    assert await kinds(board.anna) == [] and await kinds(board.outsider) == []
    ben = await _presence(db, board.ben_key)
    ben.seven_day_pct = 85.0
    await db.commit()
    assert await kinds(board.ben) == []  # no spare allowance: no offer
    assert (await _hints(db, board, board.ben_key))["available_handoffs"] == {"count": 0, "items": []}
    ben.seven_day_pct = 40.0
    await db.commit()
    assert (await _hints(db, board, board.ben_key))["available_handoffs"] == {"count": 1, "items": ["BRD-6"]}
    assert (await _hints(db, board, board.anna_key))["available_handoffs"] == {"count": 0, "items": []}
    # The holder's allowance recovers while the request stands: its own item is still never offered to it.
    anna.state, anna.seven_day_pct = "active", 10.0
    await db.commit()
    assert (await _hints(db, board, board.anna_key))["available_handoffs"] == {"count": 0, "items": []}
    assert await kinds(board.anna) == []


@pytest.mark.asyncio
async def test_handoff_confirm_reaches_the_receiver_and_admins_of_automatic_requests(client, db, board):
    takeover = await board.ben_requests(db)

    async def confirm_items(user_id):
        answer = (await _get(client, "/action-needed", user_id)).json()
        return [entry for entry in answer["items"] if entry["kind"] == "handoff_confirm"]

    [entry] = await confirm_items(board.ben)
    assert entry["takeover_id"] == takeover["id"] and entry["agent"]["user"]["id"] == board.ben
    assert entry["agent"]["agent_hash"] == session_key_hash(board.ben_key)
    assert await confirm_items(board.owner) == [] and await confirm_items(board.anna) == []
    [note] = (await db.execute(select(Notification).where(
        Notification.user_id == board.ben, Notification.type == "agent_board.handoff_confirm"))).scalars().all()
    assert note.link.endswith(f"&takeover_id={takeover['id']}") and note.body is None
    assert note.title.startswith("Confirm takeover – BRD-6")

    assert (await _decide(client, takeover["id"], board.ben)).status_code == 200
    await db.refresh(note)
    assert note.is_read is True and await confirm_items(board.ben) == []

    # A takeover after an automatic request also reaches the Workspace admins.
    from tests.agent_board.support import agent
    from tests.agent_board.work_item_claims_support import _claim

    item = await seed_item(db, board.ws, "BRD-8")
    await db.commit()
    await _claim(db, await agent(db, board.anna, session_key=board.anna_key), item)
    anna = await _presence(db, board.anna_key)
    anna.state = "limit_reached"
    await request_handoffs_for_presence(db, anna, session_key_hash(board.anna_key))
    await Pair.call(board, db, board.ben, "work_item_takeover_request", session_key=board.ben_key,
                    work_item_id=item.id)
    await db.commit()
    assert [entry["work_item"]["key"] for entry in await confirm_items(board.owner)] == ["BRD-8"]
    assert [entry["work_item"]["key"] for entry in await confirm_items(board.admin)] == ["BRD-8"]


@pytest.mark.asyncio
async def test_the_handoff_nudge_follows_writes_and_handoffs(db, board):
    def keys(hints):
        return [(entry["work_item_key"], entry["marker"]) for entry in hints["handoff_nudges"]]

    first = keys(await _hints(db, board, board.anna_key))
    assert [key for key, _ in first] == ["BRD-6"]  # claimed, no handoff yet
    await board.handoff(db, "v1")
    assert keys(await _hints(db, board, board.anna_key)) == []
    _, scope = await scope_for(db, board.anna)
    await _fenced(db, board.anna, scope, "work_item_note", {"work_item": board.item.id}, session_key=board.anna_key)
    changed = keys(await _hints(db, board, board.anna_key))
    assert [key for key, _ in changed] == ["BRD-6"] and changed[0][1] != first[0][1]
    await board.handoff(db, "v2")
    assert keys(await _hints(db, board, board.anna_key)) == []
    assert keys(await _hints(db, board, board.ben_key)) == []  # Ben holds nothing


@pytest.mark.asyncio
async def test_the_stop_answer_carries_the_hints(client, db, board):
    from tests.agent_gateway.seat_presence_support import _gateway_headers, _register

    project = await db.get(Project, board.ws)
    project.config = {**(project.config or {}), "agent_gateway_policy": {
        "verification": {"test_command_prefixes": [["pytest"]], "change_tools": ["Edit"]}, "tool_rules": []}}
    await db.commit()
    gateway = await _gateway_headers(db, board.ben, board.ws)
    assert (await _register(client, gateway, profile="governed")).status_code == 200
    answer = await client.post("/api/v1/agent-gateway/sessions/verification", json={"hook_event_name": "Stop"},
                               headers=gateway)
    body = answer.json()
    assert answer.status_code == 200
    assert body["available_handoffs"] == {"count": 0, "items": []} and body["handoff_nudges"] == []


async def _memories(db, project_id):
    rows = await db.execute(select(KnowledgeMemoryItem).where(KnowledgeMemoryItem.project_id == project_id))
    return list(rows.scalars().all())


@pytest.mark.asyncio
async def test_a_confirmed_takeover_keeps_the_handoffs_lessons_once(client, db, board):
    await Pair.call(board, db, board.anna, "work_item_handoff_write", session_key=board.anna_key,
                    work_item_id=board.item.id, sections={
                        "open_decisions": ["Keep the legacy route?"], "pitfalls": ["The cache hides the redirect"],
                        "rules": "Never touch the auth schema", "state": "not a memory"})
    await db.commit()
    takeover = await board.ben_requests(db)
    assert (await _decide(client, takeover["id"], board.ben)).status_code == 200

    items = await _memories(db, board.ws)
    by_class = {item.item_class: item for item in items}
    assert set(by_class) == {"decision", "learning", "convention"} and len(items) == 3
    assert by_class["decision"].text == "BRD-6 open decisions: Keep the legacy route?"
    assert by_class["learning"].author_class == "model_inferred" and by_class["learning"].scope == "workspace"
    assert by_class["convention"].turn_ref == f"handoff:{board.item.id}:rules"
    assert all("not a memory" not in item.text for item in items)
    assert await capture_latest_handoff_memory(db, board.item.id) == ["already_known"] * 3
    assert len(await _memories(db, board.ws)) == 3

    from app.services.knowledge.access.authorization import AuthorizedWorkspace
    from app.services.knowledge.identity.workspace import WorkspaceId
    from app.services.knowledge.memory.recall import parse_recall_request, recall

    authorized = AuthorizedWorkspace(workspace=WorkspaceId.parse(board.ws), project_id=board.ws, role="member")
    found = await recall(db, authorized=authorized, user_id=board.ben,
                         request=parse_recall_request("legacy route", None, 5))
    assert any("Keep the legacy route?" in entry["text"] for entry in found)


@pytest.mark.asyncio
async def test_a_done_item_keeps_its_lessons_and_a_change_supersedes(db, board):
    await board.handoff(db, "v1")
    await Pair.call(board, db, board.anna, "work_item_handoff_write", session_key=board.anna_key,
                    work_item_id=board.item.id, sections={"pitfalls": ["Old pitfall"]})
    assert await capture_if_done(db, board.item.id) == []  # not done yet
    item = await db.get(WorkItem, board.item.id)
    item.work_state = "done"
    await db.flush()
    assert await capture_if_done(db, board.item.id) == ["recorded"]
    await Pair.call(board, db, board.anna, "work_item_handoff_write", session_key=board.anna_key,
                    work_item_id=board.item.id, sections={"pitfalls": ["New pitfall"]})
    assert await capture_if_done(db, board.item.id) == ["recorded"]
    rows = sorted(await _memories(db, board.ws), key=lambda row: row.created_at)
    assert [(row.text, row.state) for row in rows] == [
        ("BRD-6 pitfalls: Old pitfall", "superseded"), ("BRD-6 pitfalls: New pitfall", "observed")]
    assert rows[1].supersedes_id == rows[0].id


@pytest.mark.asyncio
async def test_an_agent_transition_to_done_captures_the_lessons(db, board):
    await Pair.call(board, db, board.anna, "work_item_handoff_write", session_key=board.anna_key,
                    work_item_id=board.item.id, sections={"rules": "Ship behind a flag"})

    async def transition(session, *, user, scope, arguments):
        (await session.get(WorkItem, board.item.id)).work_state = "done"
        await session.flush()
        return {"ok": True}

    from app.services.agent_board.fencing import fenced_handlers

    _, scope = await scope_for(db, board.anna)
    user = await db.get(User, board.anna)
    handler = fenced_handlers({"work_item_transition": transition},
                              headers={"x-octryx-session": board.anna_key})["work_item_transition"]
    await handler(db, user=user, scope=scope, arguments={"work_item": board.item.id})
    assert [row.text for row in await _memories(db, board.ws)] == ["BRD-6 rules: Ship behind a flag"]


@pytest.mark.asyncio
async def test_the_test_hook_is_off_by_default_and_for_platform_admins_only(client, db, board, monkeypatch):
    body = {"project_id": board.ws, "agent_hash": session_key_hash(board.anna_key), "seven_day_pct": 95}
    monkeypatch.delenv("OCTRYX_ENABLE_TEST_HOOKS", raising=False)
    assert (await _post(client, "/test/presence-limit", board.platform_admin, body)).status_code == 404
    monkeypatch.setenv("OCTRYX_ENABLE_TEST_HOOKS", "false")
    assert (await _post(client, "/test/presence-limit", board.platform_admin, body)).status_code == 404
    monkeypatch.setenv("OCTRYX_ENABLE_TEST_HOOKS", "true")
    assert (await _post(client, "/test/presence-limit", board.owner, body)).status_code == 403
    missing = await _post(client, "/test/presence-limit", board.platform_admin, {**body, "agent_hash": "0" * 24})
    done = await _post(client, "/test/presence-limit", board.platform_admin, body)
    assert missing.status_code == 404
    assert done.status_code == 200 and done.json()["automatic_requests"] == 1 and done.json()["state"] == "active"
    assert len(await _auto_requests(db)) == 1
    audit = (await db.execute(select(func.count(AuditLog.id)).where(
        AuditLog.action == "agent_board.test.presence_limit"))).scalar_one()
    assert audit == 1 and HOOK.endswith("/test/presence-limit")
