"""Automatic requester selection: the server offers and never assigns, picks only a qualifying agent other than the holder by spare allowance and heartbeat, and moves an offer on after its timeout."""

from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import select

from app.models import AgentBoardMessage, WorkItemClaim, WorkItemTakeover
from app.services.agent_gateway.allowance import Allowance
from app.services.agent_gateway.presence import record_allowance, session_key_hash
from app.time_utils import utc_now
from tests.agent_board.auto_takeover_support import (  # noqa: F401
    AUTO,
    _auto_ready,
    _presence,
    _request,
    _set_policy,
    board,
)
from tests.agent_board.support import seed_presence


@pytest.mark.asyncio
async def test_the_server_offers_and_never_assigns(db, board):  # noqa: F811
    from app.services.agent_board.session_hints import session_handoff_hints

    await _auto_ready(db, board, holder_pct=10.0)
    await record_allowance(db, board.anna_key, Allowance(10.0, None, 95.0, None, None))
    claim = await db.get(WorkItemClaim, board.claim["claim_id"])
    await db.refresh(claim)
    request = (await db.execute(select(AgentBoardMessage).where(AgentBoardMessage.author_type == "system"))).scalar_one()
    hints = await session_handoff_hints(db, session_key=board.ben_key, agent_hash=session_key_hash(board.ben_key),
                                        project_id=board.ws)
    anna_hints = await session_handoff_hints(db, session_key=board.anna_key,
                                             agent_hash=session_key_hash(board.anna_key), project_id=board.ws)

    assert (await db.execute(select(WorkItemTakeover))).scalars().all() == []
    assert claim.released_at is None and claim.holder_ref_hash == session_key_hash(board.anna_key)
    assert claim.offer_agent_hash == request.to_agent_hash == session_key_hash(board.ben_key)
    assert hints["handoff_offers"] == ["BRD-6"] and anna_hints["handoff_offers"] == []
    assert [entry["kind"] for entry in hints["handoff_nudges"]] == ["offer"]
    asked = await _request(db, board)
    assert asked["status"] == "confirmed" and asked["decided_by"] == {"kind": "system"}


@pytest.mark.asyncio
@pytest.mark.parametrize("others", ["none", "stopped_only"])
async def test_no_pick_without_a_qualifying_agent(db, board, others):  # noqa: F811
    await _auto_ready(db, board, holder_pct=10.0)
    ben = await _presence(db, board.ben_key)
    if others in ("none", "stopped_only"):
        ben.seven_day_pct = 99.0 if others == "none" else None
        if others == "stopped_only":
            ben.stopped_at = utc_now()
    await db.commit()
    await record_allowance(db, board.anna_key, Allowance(10.0, None, 95.0, None, None))
    assert (await db.execute(select(WorkItemTakeover))).scalars().all() == []
    requests = (await db.execute(select(AgentBoardMessage).where(AgentBoardMessage.author_type == "system"))).scalars()
    assert len(requests.all()) == 1


@pytest.mark.asyncio
async def test_auto_mode_uses_its_own_threshold_for_automatic_requests(db, board):  # noqa: F811
    await _auto_ready(db, board, holder_pct=10.0, policy={**AUTO, "auto_threshold_pct": 80})
    await record_allowance(db, board.anna_key, Allowance(10.0, None, 85.0, None, None))
    requests = (await db.execute(select(AgentBoardMessage).where(
        AgentBoardMessage.author_type == "system", AgentBoardMessage.claim_id.is_not(None)))).scalars()
    assert len(requests.all()) == 1  # 85 % crosses the policy's 80 %, below the default 90 %


@pytest.mark.asyncio
async def test_the_holder_is_never_picked_as_its_own_requester(db, board):  # noqa: F811
    await _auto_ready(db, board, holder_pct=10.0, policy={**AUTO, "auto_threshold_pct": 30, "require_spare_pct": 50})
    ben = await _presence(db, board.ben_key)
    ben.stopped_at = utc_now()
    await db.commit()
    await record_allowance(db, board.anna_key, Allowance(10.0, None, 35.0, None, None))
    assert (await db.execute(select(WorkItemTakeover))).scalars().all() == []
    claim = await db.get(WorkItemClaim, board.claim["claim_id"])
    assert claim.released_at is None


@pytest.mark.asyncio
async def test_the_most_spare_allowance_wins_and_a_tie_goes_to_the_latest_heartbeat(db, board):  # noqa: F811
    await _auto_ready(db, board, holder_pct=10.0)
    ben = await _presence(db, board.ben_key)
    ben.profile, ben.seven_day_pct, ben.five_hour_pct = "seat", 30.0, 5.0
    owner_key = await seed_presence(db, board.owner, board.ws)
    owner = await _presence(db, owner_key)
    owner.profile, owner.seven_day_pct, owner.five_hour_pct = "seat", 10.0, 60.0
    await db.commit()
    await record_allowance(db, board.anna_key, Allowance(10.0, None, 95.0, None, None))
    claim = await db.get(WorkItemClaim, board.claim["claim_id"])
    await db.refresh(claim)
    assert claim.offer_agent_hash == session_key_hash(board.ben_key)
    assert (await db.execute(select(WorkItemTakeover))).scalars().all() == []


@pytest.mark.asyncio
async def test_a_tie_in_spare_allowance_goes_to_the_most_recent_heartbeat(db, board):  # noqa: F811
    await _auto_ready(db, board, holder_pct=10.0)
    ben = await _presence(db, board.ben_key)
    owner_key = await seed_presence(db, board.owner, board.ws)
    owner = await _presence(db, owner_key)
    ben.last_seen_at = utc_now() - timedelta(minutes=2)
    owner.last_seen_at = utc_now() - timedelta(minutes=1)
    await db.commit()
    await record_allowance(db, board.anna_key, Allowance(10.0, None, 95.0, None, None))
    claim = await db.get(WorkItemClaim, board.claim["claim_id"])
    await db.refresh(claim)
    assert claim.offer_agent_hash == session_key_hash(owner_key)


@pytest.mark.asyncio
async def test_an_offer_moves_on_after_the_timeout_unless_the_agent_asked(db, board):  # noqa: F811
    from app.services.agent_board.session_hints import session_handoff_hints

    await _auto_ready(db, board, holder_pct=10.0)
    owner_key = await seed_presence(db, board.owner, board.ws)
    ben, owner = await _presence(db, board.ben_key), await _presence(db, owner_key)
    ben.seven_day_pct, owner.seven_day_pct = 10.0, 20.0
    await db.commit()
    await record_allowance(db, board.anna_key, Allowance(10.0, None, 95.0, None, None))
    claim = await db.get(WorkItemClaim, board.claim["claim_id"])
    assert claim.offer_agent_hash == session_key_hash(board.ben_key)

    async def hints(key):
        return await session_handoff_hints(db, session_key=key, agent_hash=session_key_hash(key), project_id=board.ws)

    assert (await hints(owner_key))["handoff_offers"] == []
    claim.offer_at = utc_now() - timedelta(minutes=11)
    await db.flush()
    assert (await hints(owner_key))["handoff_offers"] == ["BRD-6"]
    assert (await hints(board.ben_key))["handoff_offers"] == []
    assert claim.offer_history == [session_key_hash(board.ben_key), session_key_hash(owner_key)]


@pytest.mark.asyncio
async def test_an_offer_the_agent_took_up_does_not_move(db, board):  # noqa: F811
    from app.services.agent_board.session_hints import session_handoff_hints

    await _auto_ready(db, board, holder_pct=10.0)
    owner = await _presence(db, await seed_presence(db, board.owner, board.ws))
    owner.seven_day_pct = 40.0  # a candidate, but Ben (unknown, governed) has more spare
    await db.commit()
    await record_allowance(db, board.anna_key, Allowance(10.0, None, 95.0, None, None))
    claim = await db.get(WorkItemClaim, board.claim["claim_id"])
    offered = claim.offer_agent_hash
    assert offered == session_key_hash(board.ben_key)
    await _set_policy(db, board, {**AUTO, "mode": "confirm"})
    asked = await _request(db, board)
    assert asked["status"] == "pending"
    claim.offer_at = utc_now() - timedelta(minutes=30)
    await db.flush()
    await session_handoff_hints(db, session_key=board.ben_key, agent_hash=offered, project_id=board.ws)
    assert claim.offer_agent_hash == offered
