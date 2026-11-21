"""The product boot: only the platform agents and the shipped phased workflows, idempotent."""

from __future__ import annotations

import pytest
import sqlalchemy as sa
from sqlalchemy import func, select

from app.bootstrap import seed_database
from app.models import AgentDefinition, FlowDefinition, Instruction
from app.services.platform_agents.catalog import PLATFORM_AGENT_KEYS

pytestmark = pytest.mark.asyncio
PHASED = {"jira-intake-triage", "feature-delivery-tdd", "bug-fix-reproduction", "incident-analysis"}


async def _count(db, model, *where) -> int:
    return int((await db.execute(select(func.count()).select_from(model).where(*where))).scalar() or 0)


async def test_boot_seeds_only_the_platform_items_and_is_idempotent(db):
    # Remove the test baseline's own fixtures: what remains is what the product boot itself creates.
    await db.execute(sa.delete(Instruction))
    await db.execute(sa.delete(AgentDefinition).where(AgentDefinition.builtin_key == "coding"))
    await db.flush()
    await seed_database(db)
    await seed_database(db)
    await db.flush()
    assert await _count(db, Instruction) == 0
    assert await _count(db, AgentDefinition, AgentDefinition.builtin_key == "coding") == 0
    keys = [row[0] for row in (await db.execute(select(AgentDefinition.builtin_key).where(
        AgentDefinition.builtin_key.in_(PLATFORM_AGENT_KEYS)))).all()]
    assert sorted(keys) == sorted(PLATFORM_AGENT_KEYS)
    flows = [row[0] for row in (await db.execute(select(FlowDefinition.key).where(
        FlowDefinition.key.in_(PHASED), FlowDefinition.status == "published"))).all()]
    assert sorted(flows) == sorted(PHASED)
