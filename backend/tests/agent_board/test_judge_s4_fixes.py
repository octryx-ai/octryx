"""Takeover and handoff edge cases: the requested claim only, fencing after an admin request, section keys."""

from __future__ import annotations

import pytest
from fastapi import HTTPException
from sqlalchemy import select, update

from app.models import AuditLog, WorkItemClaim, WorkItemTakeover
from app.models.security.user import UserProject
from app.services.agent_board import automation
from app.services.agent_board.claim_values import RELEASE_SESSION_STOPPED
from app.services.agent_gateway.allowance import Allowance
from app.services.agent_gateway.presence import record_allowance, session_key_hash
from app.time_utils import utc_now
from tests.agent_board.board_rest_support import _post
from tests.agent_board.support import agent, scope_for, seed_presence
from tests.agent_board.test_handoffs import Pair
from tests.agent_board.test_takeover_rest import Board
from tests.agent_board.work_item_claims_support import _claim, _fenced

AWS_KEY = "AKIA" + "IOSFODNN7EXAMPLE"


@pytest.fixture
async def board(db):
    return await Board().build(db)


async def _status(db, takeover_id) -> str:
    row = await db.get(WorkItemTakeover, takeover_id)
    await db.refresh(row)
    return row.status


async def _live(db, item_id):
    return (await db.execute(select(WorkItemClaim).where(
        WorkItemClaim.work_item_id == item_id, WorkItemClaim.released_at.is_(None)))).scalars().all()


# --- only the claim the takeover was requested against ----------------------------------------------------------


@pytest.mark.asyncio
async def test_a_confirm_cancels_the_other_requests_against_the_same_claim(client, db, board):
    owner_key = await seed_presence(db, board.owner, board.ws)
    await db.commit()
    ben = await board.ben_requests(db)
    other = (await Pair.call(board, db, board.owner, "work_item_takeover_request", session_key=owner_key,
                             work_item_id=board.item.id))["takeover"]
    await db.commit()
    assert (await _post(client, f"/takeovers/{ben['id']}/confirm", board.ben)).status_code == 200
    assert await _status(db, other["id"]) == "cancelled"
    late = await _post(client, f"/takeovers/{other['id']}/confirm", board.owner)
    assert late.status_code == 409 and late.json()["detail"] == {"code": "takeover_not_pending"}
    [live] = await _live(db, board.item.id)
    assert live.holder_ref_hash == session_key_hash(board.ben_key)


@pytest.mark.asyncio
async def test_a_confirm_after_the_holder_changed_is_cancelled_not_applied(client, db, board):
    ben = await board.ben_requests(db)
    await db.execute(update(WorkItemClaim).where(WorkItemClaim.id == board.claim["claim_id"]).values(
        released_at=utc_now(), release_reason=RELEASE_SESSION_STOPPED))
    owner_key = await seed_presence(db, board.owner, board.ws)
    await db.commit()
    await _claim(db, await agent(db, board.owner, session_key=owner_key), board.item)
    await db.commit()
    refused = await _post(client, f"/takeovers/{ben['id']}/confirm", board.ben)
    assert refused.status_code == 409 and await _status(db, ben["id"]) == "cancelled"
    [live] = await _live(db, board.item.id)
    assert live.holder_ref_hash == session_key_hash(owner_key)


@pytest.mark.asyncio
async def test_an_admin_request_made_without_a_claim_does_not_take_a_claim_made_since(client, db, board):
    await db.execute(update(WorkItemClaim).where(WorkItemClaim.id == board.claim["claim_id"]).values(
        released_at=utc_now(), release_reason=RELEASE_SESSION_STOPPED))
    await db.commit()
    made = await _post(client, "/handoff-requests", board.owner, {
        "project_id": board.ws, "work_item_id": board.item.id, "to_user_id": board.ben, "body": "please"})
    takeover_id = made.json()["takeover"]["id"]
    owner_key = await seed_presence(db, board.owner, board.ws)
    await db.commit()
    await _claim(db, await agent(db, board.owner, session_key=owner_key), board.item)
    await db.commit()
    refused = await _post(client, f"/takeovers/{takeover_id}/confirm", board.ben)
    assert refused.status_code == 409 and await _status(db, takeover_id) == "cancelled"
    assert len(await _live(db, board.item.id)) == 1


# --- the old holder stays fenced after an admin request ------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_old_holder_is_fenced_and_cannot_reclaim_until_someone_else_claims(client, db, board):
    made = await _post(client, "/handoff-requests", board.owner, {
        "project_id": board.ws, "work_item_id": board.item.id, "to_user_id": board.ben, "body": "please"})
    assert (await _post(client, f"/takeovers/{made.json()['takeover']['id']}/confirm", board.ben)).status_code == 200
    _, anna_scope = await scope_for(db, board.anna)
    with pytest.raises(HTTPException) as fenced:
        await _fenced(db, board.anna, anna_scope, "work_item_note", {"work_item": board.item.id},
                      session_key=board.anna_key)
    anna = await agent(db, board.anna, session_key=board.anna_key)
    again = await _claim(db, anna, board.item)
    assert fenced.value.detail["code"] == "claim_lost"
    assert again == {"claimed": False, "code": "claim_lost", "held_by": None}
    # Another agent may claim the free item; once it lets go, the item is ordinary again.
    ben_claim = await _claim(db, await agent(db, board.ben, session_key=board.ben_key), board.item)
    assert ben_claim["claimed"] is True
    await db.execute(update(WorkItemClaim).where(WorkItemClaim.id == ben_claim["claim_id"]).values(
        released_at=utc_now(), release_reason="released"))
    await db.flush()
    assert (await _claim(db, anna, board.item))["claimed"] is True


@pytest.mark.asyncio
async def test_other_agents_are_not_fenced_by_someone_elses_lost_claim(client, db, board):
    made = await _post(client, "/handoff-requests", board.owner, {
        "project_id": board.ws, "work_item_id": board.item.id, "to_user_id": board.ben, "body": "please"})
    await _post(client, f"/takeovers/{made.json()['takeover']['id']}/confirm", board.ben)
    _, ben_scope = await scope_for(db, board.ben, grant_id="grant-b")
    written, _ = await _fenced(db, board.ben, ben_scope, "work_item_note", {"work_item": board.item.id},
                               session_key=board.ben_key)
    assert written == {"ok": True}


# --- an unknown section key is never echoed unless it looks like a key ----------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(("key", "field"), [(AWS_KEY, "sections"), ("Bad-Key", "sections"), ("x" * 33, "sections"),
                                            ("surprise", "surprise")])
async def test_an_unknown_section_key_is_echoed_only_when_safe(db, board, key, field):
    with pytest.raises(HTTPException) as refused:
        await Pair.call(board, db, board.anna, "work_item_handoff_write", session_key=board.anna_key,
                        work_item_id=board.item.id, sections={key: "x"})
    assert refused.value.detail == {"code": "handoff_invalid", "field": field}


@pytest.mark.asyncio
async def test_a_secret_section_key_never_reaches_the_audit(db, board):
    from app.services.mcp_work_access import run_secure_work_tool
    from app.services.mcp_work_handoff_tools import handoff_tool_handlers

    with pytest.raises(HTTPException):
        await run_secure_work_tool(db, handlers=handoff_tool_handlers({"x-octryx-session": board.anna_key}),
                                   user_id=board.anna, grant_id=None, client_name="t", tool_name="work_item_handoff_write",
                                   arguments={"work_item_id": board.item.id, "sections": {AWS_KEY: "x"}})
    errors = [str((row.details or {}).get("error_detail")) for row in (await db.execute(select(AuditLog))).scalars()]
    assert errors and not any(AWS_KEY in text for text in errors)


# --- L-a: the automation never fails the seat call -----------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_failing_automation_never_fails_the_allowance_update(db, board, monkeypatch):
    async def broken(*args, **kwargs):
        raise RuntimeError("board down")

    monkeypatch.setattr("app.services.agent_gateway.presence.request_handoffs_for_presence", broken)
    await record_allowance(db, board.anna_key, Allowance(10.0, None, 95.0, None, None))
    from app.models import AgentPresence

    presence = (await db.execute(select(AgentPresence).where(AgentPresence.session_key == board.anna_key))).scalar_one()
    assert presence.seven_day_pct == 95.0
    assert automation.request_handoffs_for_presence is not broken


# --- L-b: only an interactive session decides -----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_takeover_decisions_need_an_interactive_platform_session(client, db, board):
    from app.services.agent_gateway.contract import GATEWAY_AUDIENCE, SCOPE_MODEL_INVOKE
    from app.services.auth.tokens import create_session_stream_token
    from app.services.oauth_provider import mint_access_token

    takeover = await board.ben_requests(db)
    path = f"/api/v1/agent-board/takeovers/{takeover['id']}/confirm"
    gateway, _ = mint_access_token(user_id=board.ben, client_id="octryx-claude", grant_id="g",
                                   scopes=[SCOPE_MODEL_INVOKE], resource=GATEWAY_AUDIENCE)
    mcp, _ = mint_access_token(user_id=board.ben, client_id="mcp", grant_id="g", scopes=["work:manage"],
                               resource="octryx-mcp")
    stream = create_session_stream_token(user_id=board.ben, session_id="s1")
    refused = [
        await client.post(path, headers={"Authorization": f"Bearer {token}"}) for token in (gateway, mcp, stream)
    ] + [await client.post(path, headers={"X-API-Key": "oek_anything"}),
         await client.post(f"{path[:-8]}/decline", headers={"Authorization": f"Bearer {gateway}"})]
    assert [answer.status_code for answer in refused] == [403] * 5
    assert all(answer.json()["detail"] == {"code": "interactive_session_required"} for answer in refused)
    assert await _status(db, takeover["id"]) == "pending"
    assert (await _post(client, f"/takeovers/{takeover['id']}/confirm", board.ben)).status_code == 200


# --- L-c: a requester who left the Workspace -----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_requester_who_left_the_workspace_is_refused(client, db, board):
    takeover = await board.ben_requests(db)
    membership = (await db.execute(select(UserProject).where(UserProject.user_id == board.ben))).scalar_one()
    await db.delete(membership)
    await db.commit()
    refused = await _post(client, f"/takeovers/{takeover['id']}/confirm", board.owner)
    assert refused.status_code == 409 and refused.json()["detail"] == {"code": "requester_not_member"}
    assert await _status(db, takeover["id"]) == "pending"
    claim = await db.get(WorkItemClaim, board.claim["claim_id"])
    await db.refresh(claim)
    assert claim.released_at is None


@pytest.mark.asyncio
async def test_an_ordinary_release_never_blocks_claiming_again(db, board):
    from app.services.agent_board.claims import release_own_claim

    anna = await agent(db, board.anna, session_key=board.anna_key)
    released = await release_own_claim(db, item=board.item, kind=anna.kind, ref_hash=anna.ref_hash,
                                       user_id=anna.user_id)
    assert released["released"] is True
    assert (await _claim(db, anna, board.item))["claimed"] is True


@pytest.mark.committed_db  # each request has its own session: only what the route commits is seen here
@pytest.mark.asyncio
async def test_the_cancelled_status_is_committed_by_the_route(client, db, board):
    ben = await board.ben_requests(db)
    await db.execute(update(WorkItemClaim).where(WorkItemClaim.id == board.claim["claim_id"]).values(
        released_at=utc_now(), release_reason=RELEASE_SESSION_STOPPED))
    await db.commit()
    refused = await _post(client, f"/takeovers/{ben['id']}/confirm", board.ben)
    assert refused.status_code == 409
    db.expire_all()
    assert await _status(db, ben["id"]) == "cancelled"
