"""The platform agents Assistant, Engineer and Reviewer are seeded once from code."""

from __future__ import annotations

import pytest
from sqlalchemy import func, select

from app.models import AgentDefinition, AgentDefinitionRevision, AgentStep
from app.services.platform_agents import seeds as seeds_module
from app.services.platform_agents.catalog import PLATFORM_AGENT_KEYS
from app.services.platform_agents.seeding import seed_checksum, seed_platform_agents
from app.services.platform_agents.seeds import SEEDS_BY_KEY
from app.web._helpers._routing_catalog import _list_chat_agent_catalog
from tests.agent_definition_revision_fixtures import admin_user, make_project

pytestmark = pytest.mark.asyncio


async def _row(db, key: str) -> AgentDefinition:
    return (await db.execute(select(AgentDefinition).where(AgentDefinition.builtin_key == key))).scalar_one()


async def _revisions(db, row: AgentDefinition) -> list[AgentDefinitionRevision]:
    return list((await db.execute(select(AgentDefinitionRevision).where(
        AgentDefinitionRevision.definition_id == row.id).order_by(AgentDefinitionRevision.revision_number))).scalars())


async def test_boot_seeds_three_published_global_agents_without_steps_or_workflow(db):
    rows = {key: await _row(db, key) for key in PLATFORM_AGENT_KEYS}
    expected = {"assistant": ("read_only", "general", True, "governed"),
                "engineer": ("change", "coding", True, "governed"),
                "reviewer": ("read_only", "coding", False, "none")}
    for key, row in rows.items():
        assert (row.capability_ceiling, row.runtime_preference, row.chat_selectable, row.tool_surface) == expected[key]
        assert row.project_id is None and row.is_active
        assert row.default_workflow_key is None and row.execution_mode is None and row.agent_type == "diagnosis"
        assert (await db.execute(select(func.count()).where(AgentStep.agent_id == row.id))).scalar() == 0
        revisions = await _revisions(db, row)
        assert [revision.status for revision in revisions] == ["published"]
        assert revisions[0].checksum == seed_checksum(SEEDS_BY_KEY[key])
    assert "never change code" in rows["assistant"].system_prompt
    assert "untrusted data" in rows["reviewer"].system_prompt


async def test_a_second_seed_is_a_no_op(db):
    admin = await admin_user(db)
    assert await seed_platform_agents(db, admin_user=admin) == {key: "unchanged" for key in PLATFORM_AGENT_KEYS}
    count = (await db.execute(select(func.count()).where(AgentDefinition.builtin_key.in_(PLATFORM_AGENT_KEYS)))).scalar()
    assert count == 3


async def test_an_admin_edited_agent_keeps_its_content_and_gets_a_changed_seed_as_a_draft(db, monkeypatch):
    import dataclasses

    admin = await admin_user(db)
    row = await _row(db, "assistant")
    row.system_prompt = "Admin wording."
    await db.flush()
    # The unchanged seed is already in the agent's history: nothing new to review.
    assert (await seed_platform_agents(db, admin_user=admin))["assistant"] == "admin_owned"
    changed = dataclasses.replace(SEEDS_BY_KEY["assistant"], instructions="Shipped v2 wording.")
    monkeypatch.setattr(seeds_module, "PLATFORM_AGENT_SEEDS", (changed,))
    import app.services.platform_agents.seeding as seeding

    monkeypatch.setattr(seeding, "PLATFORM_AGENT_SEEDS", (changed,))
    assert (await seed_platform_agents(db, admin_user=admin))["assistant"] == "draft"
    assert (await seed_platform_agents(db, admin_user=admin))["assistant"] == "admin_owned"
    await db.refresh(row)
    assert row.system_prompt == "Admin wording."
    drafts = [r for r in await _revisions(db, row) if r.checksum == seed_checksum(changed)]
    assert [r.status for r in drafts] == ["draft"]


async def test_a_row_still_at_an_earlier_shipped_seed_is_upgraded(db, monkeypatch):
    from app.services.agent_definition_revision_store import load_definition_steps
    from app.services.agent_definition_snapshot import build_definition_snapshot, compute_snapshot_checksum

    admin = await admin_user(db)
    row = await _row(db, "reviewer")
    row.description = "Shipped v0 description."
    await db.flush()
    earlier = compute_snapshot_checksum(build_definition_snapshot(row, await load_definition_steps(db, row.id)))
    monkeypatch.setitem(seeds_module.SHIPPED_SEED_CHECKSUMS, "reviewer", frozenset({earlier}))
    assert (await seed_platform_agents(db, admin_user=admin))["reviewer"] == "upgraded"
    await db.refresh(row)
    assert row.description == SEEDS_BY_KEY["reviewer"].description
    assert (await _revisions(db, row))[-1].status == "published"


async def test_the_composer_offers_exactly_the_chat_selectable_agents(db):
    # N2 kept them out of the composer; since the chat switch (N5) it offers exactly Assistant and Engineer.
    admin = await admin_user(db)
    project = await make_project(db)
    agents, _groups = await _list_chat_agent_catalog(db, user=admin, project_id=project.id)
    assert {str(item.get("name")) for item in agents} == {"Assistant", "Engineer"}
