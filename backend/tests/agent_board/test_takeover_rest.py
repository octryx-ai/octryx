"""Takeover confirmation in the UI, claim transfer, handoff and takeover REST."""

from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import select, update

from app.models import AgentBoardMessage, AuditLog, WorkItemClaim, WorkItemTakeover
from app.services.agent_gateway.presence import session_key_hash
from app.time_utils import utc_now
from tests.agent_board.board_rest_support import BOARD, Team, _get, _post
from tests.agent_board.support import agent, scope_for, seed_item, seed_presence
from tests.agent_board.test_handoffs import Pair
from tests.agent_board.work_item_claims_support import _claim, _fenced


class Board(Team):
    async def build(self, db):
        await super().build(db)
        self.ben_key = await seed_presence(db, self.ben, self.ws)
        self.item = await seed_item(db, self.ws, "BRD-6", title="Login redirect")
        await db.commit()
        self.claim = await _claim(db, await agent(db, self.anna, session_key=self.anna_key), self.item, paths=["src"])
        await db.commit()
        return self

    async def handoff(self, db, state="v1"):
        return await Pair.call(self, db, self.anna, "work_item_handoff_write", session_key=self.anna_key,
                               work_item_id=self.item.id, sections={"state": state})

    async def ben_requests(self, db):
        result = await Pair.call(self, db, self.ben, "work_item_takeover_request", session_key=self.ben_key,
                                 work_item_id=self.item.id, reason="Anna is at her limit")
        await db.commit()
        return result["takeover"]


@pytest.fixture
async def board(db):
    return await Board().build(db)


async def _decide(client, takeover_id, user_id, verb="confirm"):
    return await _post(client, f"/takeovers/{takeover_id}/{verb}", user_id)


@pytest.mark.asyncio
@pytest.mark.parametrize(("who", "status"), [
    ("ben", 200), ("owner", 200), ("admin", 200), ("platform_admin", 200), ("anna", 403), ("outsider", 404),
])
async def test_only_the_receiving_person_or_an_admin_confirms(client, db, board, who, status):
    takeover = await board.ben_requests(db)
    answer = await _decide(client, takeover["id"], getattr(board, who))
    assert answer.status_code == status
    if status == 200:
        assert answer.json()["takeover"]["status"] == "confirmed"
        assert answer.json()["takeover"]["decided_by"] == {
            "kind": "human", "user": answer.json()["takeover"]["decided_by"]["user"]}
        assert answer.json()["takeover"]["decided_by"]["user"]["id"] == getattr(board, who)


@pytest.mark.asyncio
@pytest.mark.parametrize(("who", "status"), [("ben", 200), ("owner", 200), ("anna", 403), ("outsider", 404)])
async def test_only_the_receiving_person_or_an_admin_declines(client, db, board, who, status):
    takeover = await board.ben_requests(db)
    answer = await _decide(client, takeover["id"], getattr(board, who), "decline")
    assert answer.status_code == status
    claim = await db.get(WorkItemClaim, board.claim["claim_id"])
    await db.refresh(claim)
    assert claim.released_at is None


@pytest.mark.asyncio
async def test_confirm_transfers_the_claim_and_fences_the_old_holder(client, db, board):
    await board.handoff(db, "v1")
    await board.handoff(db, "v2")
    await db.commit()
    takeover = await board.ben_requests(db)

    confirmed = await _decide(client, takeover["id"], board.ben)
    body = confirmed.json()
    old = await db.get(WorkItemClaim, board.claim["claim_id"])
    await db.refresh(old)
    new = (await db.execute(select(WorkItemClaim).where(
        WorkItemClaim.work_item_id == board.item.id, WorkItemClaim.released_at.is_(None)))).scalar_one()

    assert confirmed.status_code == 200 and body["handoff"]["version"] == 2
    assert body["handoff"]["sections"]["state"] == "v2" and body["viewer"]["user_id"] == board.ben
    assert (old.released_at is not None, old.release_reason) == (True, "taken_over")
    assert (new.holder_ref_hash, new.holder_user_id, new.epoch) == (
        session_key_hash(board.ben_key), board.ben, board.claim["epoch"] + 1)
    assert new.paths == ["src"] and new.lease_until > utc_now() + timedelta(seconds=800)
    assert body["takeover"]["status"] == "confirmed" and body["takeover"]["handoff"]["version"] == 2

    _, anna_scope = await scope_for(db, board.anna)
    for arguments in ({"work_item": board.item.id}, {"work_item": board.item.id, "claim_epoch": board.claim["epoch"]}):
        with pytest.raises(Exception) as fenced:
            await _fenced(db, board.anna, anna_scope, "work_item_note", arguments, session_key=board.anna_key)
        assert fenced.value.status_code == 409 and fenced.value.detail["code"] == "claim_lost"
    with pytest.raises(Exception) as handoff:
        await board.handoff(db, "v3")
    assert handoff.value.detail["code"] == "claim_lost"
    _, ben_scope = await scope_for(db, board.ben, grant_id="grant-b")
    written, _ = await _fenced(db, board.ben, ben_scope, "work_item_note", {"work_item": board.item.id,
                                                                            "claim_epoch": new.epoch},
                               session_key=board.ben_key)
    assert written == {"ok": True}

    accept = (await db.execute(select(AgentBoardMessage).where(AgentBoardMessage.kind == "handoff_accept"))).scalar_one()
    assert (accept.reply_to, accept.to_agent_hash, accept.author_type) == (
        takeover["message_id"], session_key_hash(board.ben_key), "human")
    audits = (await db.execute(select(AuditLog.user_id, AuditLog.action).where(
        AuditLog.resource_id == takeover["id"]))).all()
    assert {(board.ben, "agent_board.takeover.confirmed"), (board.anna, "agent_board.takeover.claim_transferred"),
            (board.ben, "agent_board.takeover.claim_transferred")} <= set(audits)


@pytest.mark.asyncio
async def test_confirm_and_decline_race_has_one_winner(client, db, board):
    takeover = await board.ben_requests(db)
    first = await _decide(client, takeover["id"], board.ben, "decline")
    second = await _decide(client, takeover["id"], board.owner, "confirm")
    third = await _decide(client, takeover["id"], board.ben, "decline")
    assert first.status_code == 200
    assert second.status_code == third.status_code == 409
    assert second.json()["detail"] == {"code": "takeover_not_pending"}

    from app.services.agent_board.takeovers import decide_takeover

    other = await Pair.call(board, db, board.owner, "work_item_takeover_request", grant="grant-o",
                            work_item_id=board.item.id)
    stale = await db.get(WorkItemTakeover, other["takeover"]["id"])
    assert stale.status == "pending"
    await db.execute(update(WorkItemTakeover).where(WorkItemTakeover.id == stale.id).values(status="declined")
                     .execution_options(synchronize_session=False))
    with pytest.raises(Exception) as lost:
        await decide_takeover(db, takeover=stale, user_id=board.owner, confirm=True)
    assert lost.value.detail == {"code": "takeover_not_pending"}
    claim = await db.get(WorkItemClaim, board.claim["claim_id"])
    await db.refresh(claim)
    assert claim.released_at is None


@pytest.mark.asyncio
async def test_an_expired_takeover_cannot_be_confirmed(client, db, board):
    takeover = await board.ben_requests(db)
    row = await db.get(WorkItemTakeover, takeover["id"])
    row.expires_at = utc_now() - timedelta(seconds=1)
    await db.commit()
    refused = await _decide(client, takeover["id"], board.ben)  # still stored as pending: the CAS checks the time
    listed = (await _get(client, "/takeovers", board.ben, project_id=board.ws)).json()
    assert listed["items"][0]["status"] == "expired" and refused.status_code == 409
    claim = await db.get(WorkItemClaim, board.claim["claim_id"])
    await db.refresh(claim)
    assert claim.released_at is None
    assert (await _get(client, "/takeovers", board.ben, project_id=board.ws, status="expired")).json()["items"]
    assert (await _get(client, "/takeovers", board.ben, project_id=board.ws, status="pending")).json()["items"] == []
    assert (await _get(client, "/takeovers", board.ben, project_id=board.ws, status="nope")).status_code == 422


@pytest.mark.asyncio
async def test_an_admin_handoff_request_is_a_pending_takeover_for_the_chosen_person(client, db, board):
    asked = await _post(client, "/handoff-requests", board.owner, {
        "project_id": board.ws, "work_item_id": board.item.id, "to_user_id": board.ben, "body": "Ben, please"})
    takeover = asked.json()["takeover"]
    assert asked.status_code == 200 and asked.json()["message"]["kind"] == "handoff_request"
    assert (takeover["to"]["user"]["id"], takeover["to"]["agent_hash"], takeover["status"]) == (
        board.ben, None, "pending")
    assert takeover["message_id"] == asked.json()["message"]["id"] and takeover["reason"] == "Ben, please"
    confirmed = await _decide(client, takeover["id"], board.ben)
    old = await db.get(WorkItemClaim, board.claim["claim_id"])
    await db.refresh(old)
    live = (await db.execute(select(WorkItemClaim).where(
        WorkItemClaim.work_item_id == board.item.id, WorkItemClaim.released_at.is_(None)))).scalars().all()
    assert confirmed.status_code == 200 and old.release_reason == "taken_over" and live == []
    empty = await _post(client, "/handoff-requests", board.owner, {
        "project_id": board.ws, "work_item_id": board.item.id, "to_user_id": board.ben, "body": "  "})
    assert empty.status_code == 422


@pytest.mark.asyncio
async def test_handoff_and_takeover_reads_are_for_members(client, db, board):
    other_item = await seed_item(db, board.ws, "BRD-7")
    await db.commit()
    await _claim(db, await agent(db, board.anna, session_key=board.anna_key), other_item)
    for state in ("v1", "v2"):
        await board.handoff(db, state)
    await Pair.call(board, db, board.anna, "work_item_handoff_write", session_key=board.anna_key,
                    work_item_id=other_item.id, sections={"goal": "other"})
    await board.ben_requests(db)
    await db.commit()

    latest = (await _get(client, "/handoffs", board.ben, project_id=board.ws)).json()
    versions = (await _get(client, "/handoffs", board.ben, project_id=board.ws, work_item_id=board.item.id)).json()
    one = await _get(client, f"/handoffs/{versions['items'][1]['id']}", board.ben)
    takeovers = (await _get(client, "/takeovers", board.owner, project_id=board.ws)).json()

    assert sorted((entry["work_item"]["key"], entry["version"]) for entry in latest["items"]) == [
        ("BRD-6", 2), ("BRD-7", 1)]
    assert [entry["version"] for entry in versions["items"]] == [2, 1]
    assert set(versions["items"][0]) == {"id", "work_item", "version", "author", "created_at", "sections"}
    assert one.json()["version"] == 1 and one.json()["viewer"] == {"user_id": board.ben, "can_admin": False}
    assert latest["viewer"]["user_id"] == board.ben and takeovers["viewer"]["can_admin"] is True
    item = takeovers["items"][0]
    assert {"id", "work_item", "from", "to", "status", "reason", "expires_at", "created_at", "decided_at",
            "decided_by", "handoff"} <= set(item)
    assert item["handoff"]["version"] == 2
    for path, params in (("/handoffs", {"project_id": board.ws}), ("/takeovers", {"project_id": board.ws}),
                         (f"/handoffs/{versions['items'][0]['id']}", {}), ("/handoffs", {"project_id": "nope"})):
        assert (await _get(client, path, board.outsider, **params)).status_code == 404, path
    foreign = await _get(client, "/handoffs", board.ben, project_id=board.ws, work_item_id="missing")
    assert foreign.status_code == 404
    assert BOARD == "/api/v1/agent-board"
