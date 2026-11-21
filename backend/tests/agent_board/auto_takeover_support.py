"""Shared helpers for the test_auto_takeover_* modules."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.models import AgentPresence, Project
from tests.agent_board.test_handoffs import Pair
from tests.agent_board.test_takeover_rest import Board

AUTO = {"mode": "auto", "auto_threshold_pct": 90, "require_spare_pct": 50, "allowed_requesters": "members"}


@pytest.fixture
async def board(db):
    return await Board().build(db)


async def _presence(db, session_key) -> AgentPresence:
    return (await db.execute(select(AgentPresence).where(AgentPresence.session_key == session_key))).scalar_one()


async def _set_policy(db, board, policy: dict) -> None:
    project = await db.get(Project, board.ws)
    stored = dict((project.config or {}).get("agent_gateway_policy") or {})
    project.config = {**(project.config or {}), "agent_gateway_policy": {**stored, "handoff": policy}}
    await db.commit()


async def _auto_ready(db, board, *, holder_pct=95.0, policy=None) -> None:
    await _set_policy(db, board, policy or AUTO)
    anna = await _presence(db, board.anna_key)
    anna.seven_day_pct = holder_pct
    await board.handoff(db, "v1")
    await db.commit()


async def _request(db, board, *, user=None, key=None):
    result = await Pair.call(board, db, user or board.ben, "work_item_takeover_request",
                             session_key=key or board.ben_key, work_item_id=board.item.id, reason="spare here")
    await db.commit()
    return result["takeover"]
