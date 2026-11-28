"""handoff_now fires once per crossing, follows the policy trigger and the governed budget, rides on the hook answers, and "Hand over now" asks exactly the holder session."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app.models import AgentBoardMessage, AgentPresence, Project, WorkItem, WorkItemTakeover
from app.services.agent_board.handoff_trigger import handoff_now
from app.services.agent_gateway.daily_budget import DailyBudgetDecision
from app.time_utils import utc_now
from tests.agent_board.client_handoff_support import BASE, _headers, board  # noqa: F401
from tests.agent_gateway.seat_presence_support import _gateway_headers


async def _presence(db, session_key) -> AgentPresence:
    return (await db.execute(select(AgentPresence).where(AgentPresence.session_key == session_key))).scalar_one()


@pytest.mark.asyncio
async def test_handoff_now_fires_once_per_crossing_for_a_seat_session(db, board):  # noqa: F811
    anna = await _presence(db, board.anna_key)
    anna.profile, anna.seven_day_pct = "seat", 98.0
    assert await handoff_now(db, session_key=board.anna_key) == {}
    anna.five_hour_pct = 99.0
    first = await handoff_now(db, session_key=board.anna_key)
    again = await handoff_now(db, session_key=board.anna_key)
    assert first["handoff_now"] is True and first == again
    assert first["handoff_trigger_pct"] == 99.0
    anna.five_hour_pct = 20.0
    assert await handoff_now(db, session_key=board.anna_key) == {}
    assert anna.handoff_crossing_at is None
    anna.seven_day_pct = 99.5
    anna.handoff_crossing_at = None
    later = utc_now() + timedelta(seconds=1)
    import app.services.agent_board.handoff_trigger as trigger

    original = trigger.utc_now
    trigger.utc_now = lambda: later
    try:
        second = await handoff_now(db, session_key=board.anna_key)
    finally:
        trigger.utc_now = original
    assert second["handoff_now"] is True and second["handoff_crossing"] != first["handoff_crossing"]


@pytest.mark.asyncio
async def test_handoff_now_follows_the_policy_trigger_and_the_governed_budget(db, board, monkeypatch):  # noqa: F811
    project = await db.get(Project, board.ws)
    project.config = {**(project.config or {}), "agent_gateway_policy": {"handoff": {"auto_trigger_pct": 80}}}
    anna = await _presence(db, board.anna_key)
    anna.profile, anna.seven_day_pct = "seat", 85.0
    await db.flush()
    assert (await handoff_now(db, session_key=board.anna_key))["handoff_now"] is True
    ben = await _presence(db, board.ben_key)

    async def budget(_db, *, user_id, workspace_id, now=None):
        return DailyBudgetDecision("allowed", "", Decimal("10"), Decimal(spent), None)

    import app.services.agent_gateway.daily_budget as daily_budget

    monkeypatch.setattr(daily_budget, "check_daily_budget", budget)
    spent = "7.9"
    assert "handoff_now" not in await handoff_now(db, session_key=board.ben_key)
    spent = "8.0"
    assert (await handoff_now(db, session_key=board.ben_key))["handoff_now"] is True
    ben.stopped_at = utc_now()
    assert "handoff_now" not in await handoff_now(db, session_key=board.ben_key)


@pytest.mark.asyncio
async def test_the_hook_answers_carry_handoff_now(client, db, board):  # noqa: F811
    project = await db.get(Project, board.ws)
    project.config = {**(project.config or {}), "agent_gateway_policy": {
        "verification": {"test_command_prefixes": [["pytest"]], "change_tools": ["Edit"]}, "tool_rules": []}}
    await db.commit()
    from tests.agent_gateway.seat_presence_support import _register

    gateway = await _gateway_headers(db, board.ben, board.ws)
    assert (await _register(client, gateway, profile="governed")).status_code == 200
    stop = await client.post("/api/v1/agent-gateway/sessions/verification", json={"hook_event_name": "Stop"},
                             headers=gateway)
    assert stop.status_code == 200 and "handoff_now" not in stop.json()
    presence = await _presence(db, gateway["x-octryx-session"])
    presence.profile, presence.seven_day_pct = "seat", 99.5
    await db.commit()
    crossed = (await client.post("/api/v1/agent-gateway/sessions/verification", json={"hook_event_name": "Stop"},
                                 headers=gateway)).json()
    tool = (await client.post("/api/v1/agent-gateway/sessions/tool-check", json={
        "hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_input": {"command": "ls"}}, headers=gateway)).json()
    assert crossed["handoff_now"] is True and tool["handoff_now"] is True
    assert crossed["handoff_crossing"] == tool["handoff_crossing"]
    assert (await db.execute(select(func.count(WorkItem.id)))).scalar_one() >= 1
    assert (await db.execute(select(func.count(WorkItemTakeover.id)))).scalar_one() == 0


@pytest.mark.asyncio
async def test_hand_over_now_posts_the_request_and_asks_the_holder_session_once(client, db, board):  # noqa: F811
    from tests.agent_board.board_rest_support import _post

    path = f"/claims/{board.claim['claim_id']}/hand-over-now"
    by_member = await _post(client, path, board.ben)
    by_outsider = await _post(client, path, board.outsider)
    asked = await _post(client, path, board.owner)
    hint = await handoff_now(db, session_key=board.anna_key)

    assert (by_member.status_code, by_outsider.status_code) == (403, 404)
    assert asked.status_code == 200 and asked.json()["session_asked"] is True
    assert hint["handoff_now"] is True and hint["handoff_crossing"].startswith("requested-")
    assert "handoff_now" not in await handoff_now(db, session_key=board.ben_key)
    requests = (await db.execute(select(AgentBoardMessage).where(AgentBoardMessage.author_type == "system"))).scalars()
    assert len(requests.all()) == 1
    await client.post(f"{BASE}/commit", json={"work_item_id": "BRD-6", "repo": {}, "git": {}},
                      headers=await _headers(db, board))
    presence = await _presence(db, board.anna_key)
    await db.refresh(presence)
    assert presence.handoff_requested_at is None and await handoff_now(db, session_key=board.anna_key) == {}


@pytest.mark.asyncio
async def test_hand_over_now_asks_exactly_the_holder_session(client, db, board):  # noqa: F811
    from tests.agent_board.board_rest_support import _post
    from tests.agent_board.support import agent, seed_item
    from tests.agent_board.work_item_claims_support import _claim

    item = await seed_item(db, board.ws, "BRD-12")
    await db.commit()
    claim = await _claim(db, await agent(db, board.ben, session_key=board.ben_key), item)
    await db.commit()
    assert (await _post(client, f"/claims/{claim['claim_id']}/hand-over-now", board.owner)).status_code == 200
    assert (await handoff_now(db, session_key=board.ben_key))["handoff_now"] is True
    assert "handoff_now" not in await handoff_now(db, session_key=board.anna_key)


@pytest.mark.asyncio
async def test_a_failing_handoff_now_never_costs_a_tool_call(client, db, board, monkeypatch):  # noqa: F811
    project = await db.get(Project, board.ws)
    project.config = {**(project.config or {}), "agent_gateway_policy": {
        "verification": {"test_command_prefixes": [["pytest"]], "change_tools": ["Edit"]}, "tool_rules": []}}
    await db.commit()
    from tests.agent_gateway.seat_presence_support import _register

    gateway = await _gateway_headers(db, board.ben, board.ws)
    assert (await _register(client, gateway, profile="governed")).status_code == 200

    async def broken(*args, **kwargs):
        raise RuntimeError("trigger down")

    monkeypatch.setattr("app.services.agent_board.handoff_trigger.handoff_now", broken)
    tool = await client.post("/api/v1/agent-gateway/sessions/tool-check", json={
        "hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_input": {"command": "ls"}}, headers=gateway)
    stop = await client.post("/api/v1/agent-gateway/sessions/verification", json={"hook_event_name": "Stop"},
                             headers=gateway)
    assert tool.status_code == 200 and tool.json()["decision"] == "allow" and "handoff_now" not in tool.json()
    assert stop.status_code == 200 and "handoff_now" not in stop.json()
