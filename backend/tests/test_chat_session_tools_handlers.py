"""The chat runs the client's handlers: backlog reads, confirmed transitions, prepared turns, claims and hand-offs."""

from __future__ import annotations

import pytest

from app.services.governed_default_tool_sets import governed_default_tool_set
from app.tools.context import ToolContext
from tests.chat_session_tools_support import ACTIVE, CHAT_STATE, _confirmed_again, chat_context  # noqa: F401


@pytest.fixture
def handler_calls(monkeypatch):
    from app.services import mcp_secure_work_tools

    calls: list[tuple[str, dict]] = []

    def recorder(name):
        async def handler(db, *, user, scope, arguments):
            calls.append((name, dict(arguments)))
            return {"ok": name}
        return handler

    for name in ("work_item_list", "work_item_transition"):
        monkeypatch.setitem(mcp_secure_work_tools.MCP_SECURE_WORK_TOOL_HANDLERS, name, recorder(name))
    return calls




async def _confirmed(db, user_id: str, name: str, params: dict, context):
    from app.tools.registry import execute_tool

    held = await execute_tool(name, params, context)
    return await _confirmed_again(db, user_id, held, name, params, context)


@pytest.fixture
async def member_chat(db):
    import uuid

    from app.models import Session as AgentSession
    from tests.agent_board.support import seed_item, seed_presence
    from tests.agent_gateway.seat_presence_support import _workspace
    from tests.knowledge_evidence_seed_support import seed_member

    workspace_id = await _workspace(db)
    anna = await seed_member(db, workspace_id=workspace_id, role="member", username=f"anna{uuid.uuid4().hex[:6]}")
    ben = await seed_member(db, workspace_id=workspace_id, role="member", username=f"ben{uuid.uuid4().hex[:6]}")
    session = AgentSession(id=str(uuid.uuid4()), user_id=anna, project_id=workspace_id, agent_type="chat",
                           status="active")
    db.add(session)
    items = [await seed_item(db, workspace_id, key=f"BRD-{n}", title=f"Fix login {n}") for n in (1, 2)]
    ben_session = await seed_presence(db, ben, workspace_id)
    await db.commit()
    context = ToolContext(user_id=anna, project_ids=[workspace_id], roles=["member"], session_id=session.id,
                          project_config={}, db=db, agent_mode_key="diagnosis", capability_type="diagnosis",
                          run_capability=dict(CHAT_STATE))
    return {"workspace": workspace_id, "anna": anna, "ben": ben, "items": items, "context": context,
            "ben_session": ben_session}


@pytest.mark.asyncio
async def test_a_chat_reads_the_backlog_through_the_clients_handler_without_asking(chat_context, handler_calls):  # noqa: F811
    from app.tools.registry import execute_tool

    _user, context = chat_context
    assert await execute_tool("work_item_list", {"mine": True}, context) == {"ok": "work_item_list"}
    assert handler_calls == [("work_item_list", {"mine": True})]


@pytest.mark.asyncio
async def test_a_chat_transition_runs_the_clients_handler_only_after_the_person_confirms(
    db, chat_context, handler_calls  # noqa: F811
):
    from app.tools.capability_requirements import tool_required_capability
    from app.tools.registry import execute_tool
    from tests.agent_board.support import seed_item
    from tests.agent_gateway.seat_presence_support import _workspace

    user, context = chat_context
    item = await seed_item(db, await _workspace(db), key="OCX-7")
    move = {"work_item": item.id, "to_state": "in_progress"}
    held = await execute_tool("work_item_transition", move, context)
    assert held["code"] == "write_plan_required" and handler_calls == []

    assert await _confirmed_again(db, user.id, held, "work_item_transition", move, context) == {
        "ok": "work_item_transition"}
    assert handler_calls == [("work_item_transition", move)]
    # Platform state: a read-only chat may run it (confirmed); it is no connector delivery.
    assert tool_required_capability("work_item_transition") == "read_only"




@pytest.mark.asyncio
async def test_a_chat_claims_as_its_own_agent_and_a_client_session_then_sees_it_held(db, member_chat):
    from app.services.agent_board.identity import chat_session_identity
    from app.services.mcp_work_claim_tools import work_claim_tool_handlers
    from app.tools.registry import execute_tool
    from tests.agent_board.support import agent, scope_for

    m = member_chat
    item = m["items"][0]
    claimed = await _confirmed(db, m["anna"], "work_item_claim", {"work_item_id": item.source_key}, m["context"])
    assert claimed["claimed"] is True and claimed["epoch"] == 1

    chat = chat_session_identity(user_id=m["anna"], session_id=m["context"].session_id,
                                 project_ids=m["context"].project_ids)
    assert chat.kind == "chat_session" and chat.project_id == m["workspace"]
    ben, scope = await scope_for(db, m["ben"])
    client = await agent(db, m["ben"], session_key=m["ben_session"])
    refused = await work_claim_tool_handlers(identity=client)["work_item_claim"](
        db, user=ben, scope=scope, arguments={"work_item_id": item.id})
    assert refused["claimed"] is False

    # Reads are free: no approval is asked.
    who = await execute_tool("who_is_working_on", {"query": item.source_key}, m["context"])
    [holder] = [claim["holder"] for claim in who["claims"]]
    assert holder["kind"] == "chat_session" and holder["agent_hash"] == chat.ref_hash


@pytest.mark.asyncio
async def test_a_chat_cannot_write_through_another_agents_claim(db, member_chat, monkeypatch):
    from app.services import mcp_secure_work_tools
    from app.services.mcp_work_claim_tools import work_claim_tool_handlers
    from tests.agent_board.support import agent, scope_for

    m = member_chat
    item = m["items"][1]
    ben, scope = await scope_for(db, m["ben"])
    client = await agent(db, m["ben"], session_key=m["ben_session"])
    await work_claim_tool_handlers(identity=client)["work_item_claim"](
        db, user=ben, scope=scope, arguments={"work_item_id": item.id})
    ran = []

    async def transition(db, *, user, scope, arguments):
        ran.append(arguments)
        return {"ok": True}

    monkeypatch.setitem(mcp_secure_work_tools.MCP_SECURE_WORK_TOOL_HANDLERS, "work_item_transition", transition)
    answer = await _confirmed(db, m["anna"], "work_item_transition",
                              {"work_item": item.id, "to_state": "in_progress"}, m["context"])
    assert answer["status_code"] == 409 and "claimed_by_other" in answer["error"] and ran == []


@pytest.mark.asyncio
async def test_a_chat_posts_hands_off_and_asks_for_a_takeover_each_confirmed(db, member_chat):
    from app.tools.registry import execute_tool

    m = member_chat
    mine, theirs = m["items"]
    posted = await _confirmed(db, m["anna"], "board_post", {"kind": "info", "body": "Starting on login."},
                              m["context"])
    assert posted["message"]["project_id"] == m["workspace"], "the chat's Workspace is the post's default"
    board = await execute_tool("board_read", {}, m["context"])
    assert [message["body"] for message in board["items"]] == ["Starting on login."]

    await _confirmed(db, m["anna"], "work_item_claim", {"work_item_id": mine.id}, m["context"])
    written = await _confirmed(db, m["anna"], "work_item_handoff_write",
                               {"work_item_id": mine.id, "sections": {"goal": "Fix the login redirect"}},
                               m["context"])
    assert written["version"] == 1
    read = await execute_tool("work_item_handoff_read", {"work_item_id": mine.id}, m["context"])
    assert read["handoff"]["sections"]["goal"] == "Fix the login redirect"

    from app.services.mcp_work_claim_tools import work_claim_tool_handlers
    from tests.agent_board.support import agent, scope_for

    ben, scope = await scope_for(db, m["ben"])
    await work_claim_tool_handlers(identity=await agent(db, m["ben"], session_key=m["ben_session"]))[
        "work_item_claim"](db, user=ben, scope=scope, arguments={"work_item_id": theirs.id})
    asked = await _confirmed(db, m["anna"], "work_item_takeover_request",
                             {"work_item_id": theirs.id, "reason": "Ben is on holiday"}, m["context"])
    status = await execute_tool("work_item_takeover_status", {"takeover_id": asked["takeover"]["id"]}, m["context"])
    assert status["takeover"]["status"] == asked["takeover"]["status"]


def test_the_chat_set_offers_the_clients_coordination_tools():
    from app.tools.capability_requirements import tool_required_capability
    from app.tools.definitions import get_tool_definition_metadata

    tools = set(governed_default_tool_set("diagnosis").tools)
    reads = {"board_read", "who_is_working_on", "agent_presence_list", "work_item_handoff_read",
             "work_item_takeover_status"}
    writes = {"board_post", "board_ack", "work_item_claim", "work_item_release", "work_item_handoff_write",
              "work_item_takeover_request"}
    assert reads | writes <= tools
    assert {name for name in reads | writes if get_tool_definition_metadata(name).risk == "write"} == writes
    assert {tool_required_capability(name) for name in writes} == {"read_only"}
