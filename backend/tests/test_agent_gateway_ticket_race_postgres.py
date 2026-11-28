from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from pathlib import Path

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.bootstrap import seed_database
from app.models import ToolCall
from app.services.agent_gateway.confirmation import (
    TOOL_CALL_STATUS_CONFIRMATION_CONSUMED,
    ask_for_confirmation,
    redeem_confirmation_ticket,
)
from app.services.agent_gateway.decision_confirmation import WORKFLOW_DECIDE_HOOK_TOOL, redeem_decision_ticket
from app.services.workflow_runs.octryx.decisions import arguments_digest
from tests.agent_gateway_hook_support import confirm_hook_input
from tests.alembic_model_parity_support import migrated_database, requires_postgres
from tests.scripted_pool_support import scripted_pool  # noqa: F401 - fixture
from tests.services.agent_gateway.test_agent_gateway_confirmation_security import _setup
from tests.test_workflow_run_octryx_decisions import CONFIRM, _terminal

pytestmark = [requires_postgres, pytest.mark.usefixtures("scripted_pool")]

Redeem = Callable[[AsyncSession], Awaitable[bool]]
WAIT_SECONDS = 30.0


async def _waits_on_a_lock(maker: async_sessionmaker, racing: asyncio.Task) -> bool:
    # A loaded gate may need a while before the second redemption reaches the row the first one holds.
    loop = asyncio.get_running_loop()
    deadline = loop.time() + WAIT_SECONDS
    async with maker() as observer:
        while not racing.done() and loop.time() < deadline:
            waiting = (await observer.execute(text(
                "SELECT count(*) FROM pg_stat_activity WHERE datname = current_database() AND wait_event_type = 'Lock'"
            ))).scalar_one()
            await observer.rollback()
            if waiting:
                return True
            await asyncio.sleep(0.05)
    return False


async def _race(maker: async_sessionmaker, redeem: Redeem) -> tuple[bool, bool, bool]:
    async with maker() as first, maker() as second:
        won_first = await redeem(first)
        racing = asyncio.create_task(redeem(second))
        blocked = await _waits_on_a_lock(maker, racing)
        await first.commit()
        won_second = await racing
        await second.commit()
    return won_first, won_second, blocked


async def _confirmation_race(url: str) -> tuple[tuple[bool, bool, bool], str]:
    engine = create_async_engine(url)
    try:
        maker = async_sessionmaker(engine, expire_on_commit=False)
        async with maker() as db:
            await seed_database(db)
            _, _, gateway, session_key, _, approval_id, key = await _setup(db)
            hook_input = confirm_hook_input(key, session_key=session_key, approval_id=approval_id)
            asked = await ask_for_confirmation(db, session=gateway, session_key=session_key, hook_input=hook_input)
            await db.commit()
        values = {"approval_id": approval_id, "ticket": asked["confirmation_ticket"],
                  "tool_use_id": hook_input["tool_use_id"]}
        outcome = await _race(maker, lambda db: redeem_confirmation_ticket(db, session=gateway, **values))
        async with maker() as db:
            status = (await db.execute(select(ToolCall.status).where(
                ToolCall.session_id == gateway.id, ToolCall.parameters["approval_id"].as_string() == approval_id,
            ))).scalar_one()
        return outcome, status
    finally:
        await engine.dispose()


async def _decision_race(url: str) -> tuple[tuple[bool, bool, bool], str]:
    engine = create_async_engine(url)
    try:
        maker = async_sessionmaker(engine, expire_on_commit=False)
        async with maker() as db:
            await seed_database(db)
            terminal = await _terminal(db, CONFIRM)
            tool_input = {"action": "confirm", "payload_hash": terminal.run.node_state["waiting"]["payload_hash"]}
            ticket = (await terminal.pre_tool_use(tool_input))["confirmation_ticket"]
            await db.commit()
        gateway = terminal.gateway
        values = {"run_id": terminal.run.id, "action": "confirm", "payload_hash": tool_input["payload_hash"],
                  "arguments_digest": arguments_digest(tool_input), "ticket": ticket, "tool_use_id": "toolu_decide_1"}
        outcome = await _race(maker, lambda db: redeem_decision_ticket(db, session=gateway, **values))
        async with maker() as db:
            status = (await db.execute(select(ToolCall.status).where(
                ToolCall.session_id == gateway.id, ToolCall.tool_name == WORKFLOW_DECIDE_HOOK_TOOL,
            ))).scalar_one()
        return outcome, status
    finally:
        await engine.dispose()


def test_two_racing_redemptions_of_one_confirmation_ticket_let_exactly_one_win(tmp_path: Path):
    with migrated_database("postgresql", tmp_path) as database:
        (won_first, won_second, blocked), status = asyncio.run(_confirmation_race(database.url))
    assert (won_first, won_second, blocked) == (True, False, True)
    assert status == TOOL_CALL_STATUS_CONFIRMATION_CONSUMED


def test_two_racing_redemptions_of_one_decision_ticket_let_exactly_one_win(tmp_path: Path):
    with migrated_database("postgresql", tmp_path) as database:
        (won_first, won_second, blocked), status = asyncio.run(_decision_race(database.url))
    assert (won_first, won_second, blocked) == (True, False, True)
    assert status == TOOL_CALL_STATUS_CONFIRMATION_CONSUMED
