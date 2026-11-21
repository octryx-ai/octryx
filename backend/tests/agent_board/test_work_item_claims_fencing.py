"""Agent writes, change-plan decisions and the MCP protocol dispatch are fenced by the work-item claim, while reads are not."""

from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException

from app.models import WorkChangePlan
from app.services.agent_board.fencing import fenced_handlers
from tests.agent_board.support import agent, scope_for, seed_item, seed_presence
from tests.agent_board.work_item_claims_support import _claim, _code, _fenced, _two_members


@pytest.mark.asyncio
@pytest.mark.parametrize("tool", ["work_item_transition", "work_item_note", "change_units_plan", "change_plan_generate"])
async def test_agent_writes_are_fenced_by_the_claim(db, tool):
    workspace_id, anna, ben = await _two_members(db)
    item = await seed_item(db, workspace_id)
    session_key = await seed_presence(db, anna, workspace_id)
    holder = await agent(db, anna, session_key=session_key)
    _, anna_scope = await scope_for(db, anna, grant_id="grant-a")
    _, ben_scope = await scope_for(db, ben, grant_id="grant-b")

    free, _ = await _fenced(db, ben, ben_scope, tool, {"work_item": item.id})
    with pytest.raises(HTTPException) as no_claim_epoch:
        await _fenced(db, ben, ben_scope, tool, {"work_item": item.id, "claim_epoch": 1})
    epoch = (await _claim(db, holder, item))["epoch"]
    with pytest.raises(HTTPException) as other:
        await _fenced(db, ben, ben_scope, tool, {"work_item": item.id})
    with pytest.raises(HTTPException) as other_with_epoch:
        await _fenced(db, ben, ben_scope, tool, {"work_item": item.id, "claim_epoch": epoch})
    with pytest.raises(HTTPException) as same_user_other_agent:
        await _fenced(db, anna, anna_scope, tool, {"work_item": item.id, "claim_epoch": epoch})
    with pytest.raises(HTTPException) as stale:
        await _fenced(db, anna, anna_scope, tool, {"work_item": item.id, "claim_epoch": epoch + 1},
                      session_key=session_key)
    own, calls = await _fenced(db, anna, anna_scope, tool, {"work_item": item.id, "claim_epoch": epoch},
                               session_key=session_key)
    own_without_epoch, _ = await _fenced(db, anna, anna_scope, tool, {"work_item": item.id}, session_key=session_key)

    assert free == own == own_without_epoch == {"ok": True}
    assert calls == [{"work_item": item.id}]
    assert _code(no_claim_epoch) == (409, "claim_lost")
    assert _code(other) == (409, "claimed_by_other")
    assert other.value.detail["held_by"]["agent_hash"] == holder.ref_hash
    assert _code(other_with_epoch) == (409, "claim_lost") and "held_by" in other_with_epoch.value.detail
    assert _code(same_user_other_agent) == (409, "claim_lost")
    assert _code(stale) == (409, "claim_lost")


@pytest.mark.asyncio
async def test_a_change_plan_decision_is_fenced_through_its_work_item(db):
    workspace_id, anna, ben = await _two_members(db)
    item = await seed_item(db, workspace_id)
    plan = WorkChangePlan(id=str(uuid.uuid4()), work_item_id=item.id, title="Plan", created_by=anna)
    db.add(plan)
    await db.flush()
    await _claim(db, await agent(db, anna), item)
    _, ben_scope = await scope_for(db, ben, grant_id="grant-b")
    with pytest.raises(HTTPException) as other:
        await _fenced(db, ben, ben_scope, "change_plan_decide", {"change_plan_id": plan.id})
    assert _code(other) == (409, "claimed_by_other")
    with pytest.raises(HTTPException) as missing:
        await _fenced(db, ben, ben_scope, "change_plan_decide", {"change_plan_id": "nope"})
    assert missing.value.status_code == 404


@pytest.mark.asyncio
async def test_reads_are_not_fenced_and_a_bad_epoch_is_refused(db):
    workspace_id, anna, ben = await _two_members(db)
    item = await seed_item(db, workspace_id)
    await _claim(db, await agent(db, anna), item)
    _, ben_scope = await scope_for(db, ben, grant_id="grant-b")
    found, _ = await _fenced(db, ben, ben_scope, "work_item_find", {"work_item": item.id})
    with pytest.raises(HTTPException) as bad:
        await _fenced(db, ben, ben_scope, "work_item_note", {"work_item": item.id, "claim_epoch": "1"})
    assert found == {"ok": True} and bad.value.status_code == 422


def test_the_protocol_dispatch_fences_the_five_write_tools():
    from app.services.agent_board.fencing import FENCED_TOOLS
    from app.services.mcp_secure_work_tools import MCP_SECURE_WORK_TOOL_HANDLERS

    wrapped = fenced_handlers(MCP_SECURE_WORK_TOOL_HANDLERS, headers={})
    assert FENCED_TOOLS == {"work_item_transition", "work_item_note", "change_units_plan", "change_plan_generate",
                            "change_plan_decide"}
    assert {name for name, handler in wrapped.items() if handler is not MCP_SECURE_WORK_TOOL_HANDLERS[name]} == \
        FENCED_TOOLS


@pytest.mark.asyncio
async def test_the_mcp_protocol_dispatches_secure_work_tools_through_the_fence(monkeypatch):
    from app.services import mcp_knowledge_protocol as protocol
    from app.services.mcp_secure_work_tools import MCP_SECURE_WORK_TOOL_HANDLERS

    seen = {}

    async def capture(db, *, handlers, **kwargs):
        seen.update(handlers)
        return {}

    monkeypatch.setattr(protocol, "_authenticated_context", lambda ctx: ("user-1", None, "grant-1", ("work:manage",)))
    monkeypatch.setattr(protocol, "run_secure_work_tool", capture)
    await protocol._call_secure_work_tool(None, "work_item_note", {"work_item": "BRD-1"})
    assert seen["work_item_note"] is not MCP_SECURE_WORK_TOOL_HANDLERS["work_item_note"]
    assert seen["work_item_find"] is MCP_SECURE_WORK_TOOL_HANDLERS["work_item_find"]
