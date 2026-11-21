"""Which workflows Octryx ships, as seed data:

- default, active on a fresh installation: bug-fix-reproduction, epic-delivery ("Story / epic delivery"), spec-writing,
  pr-review-bot, pr-review-explain;
- optional, shipped switched off (an admin switches one on): pr-fix, jira-intake-triage, incident-analysis,
  team-delivery;
- never seeded: feature-delivery-tdd (the base of the accepted-spec engineering graph; the suite publishes it).
"""

from __future__ import annotations

import pytest
from sqlalchemy import delete, select

from app.models import FlowDefinition, FlowDefinitionVersion
from app.services.workflow_runs.seeding import (
    AVAILABILITY_OPTIONAL,
    phased_seeds,
    seed_phased_workflows,
)
from tests.phased_workflow_fixtures import admin_user

DEFAULT = {"bug-fix-reproduction", "epic-delivery", "spec-writing", "pr-review-bot", "pr-review-explain"}
OPTIONAL = {"pr-fix", "jira-intake-triage", "incident-analysis", "team-delivery"}
REMOVED = {"feature-delivery-tdd"}


def test_the_seed_data_says_what_ships():
    availability = {seed["key"]: seed["availability"] for seed in phased_seeds()}
    assert {key for key, value in availability.items() if value == "default"} == DEFAULT
    assert {key for key, value in availability.items() if value == AVAILABILITY_OPTIONAL} == OPTIONAL
    assert not REMOVED & set(availability)
    assert next(seed for seed in phased_seeds() if seed["key"] == "epic-delivery")["name"] == "Story / epic delivery"


async def _shipped(db) -> dict[str, FlowDefinition]:
    rows = (await db.execute(select(FlowDefinition).where(FlowDefinition.project_id.is_(None)))).scalars().all()
    return {row.key: row for row in rows if row.key in DEFAULT | OPTIONAL | REMOVED}


@pytest.mark.asyncio
async def test_a_fresh_installation_has_the_defaults_on_the_optional_off_and_nothing_removed(db):
    ids = [row.id for row in (await _shipped(db)).values()]
    await db.execute(delete(FlowDefinitionVersion).where(FlowDefinitionVersion.flow_id.in_(ids)))
    await db.execute(delete(FlowDefinition).where(FlowDefinition.id.in_(ids)))
    await db.flush()

    await seed_phased_workflows(db, admin_user=await admin_user(db))
    flows = await _shipped(db)
    assert {key for key, flow in flows.items() if flow.is_active} == DEFAULT
    assert {key for key, flow in flows.items() if not flow.is_active} == OPTIONAL
    assert not REMOVED & set(flows)
    assert all(flow.current_version_id for flow in flows.values())  # the optional ones are published, just off


@pytest.mark.asyncio
async def test_an_installation_keeps_what_it_has_and_its_own_switches(db):
    flows = await _shipped(db)  # the suite's baseline: every shipped workflow, all switched on, and B
    flows["team-delivery"].is_active = True
    await db.flush()

    await seed_phased_workflows(db, admin_user=await admin_user(db))
    after = await _shipped(db)
    assert set(after) & REMOVED == {"feature-delivery-tdd"}  # the explicitly published B is kept
    assert after["team-delivery"].is_active  # the installation's own switch stays


@pytest.mark.asyncio
async def test_a_run_shows_its_workflows_current_name_not_one_derived_from_the_key(db):
    """The run view carries the definition's name, so a renamed shipped workflow ("Story / epic delivery") shows its
    current name, not a stale one."""
    from app.models import WorkflowRun
    from app.services.workflow_runs.views import run_view

    admin = await admin_user(db)
    run = WorkflowRun(project_id=None, workflow_kind="phased", workflow_key="epic-delivery", title="OCX-2",
                      requested_by=admin.id, status="running")
    db.add(run)
    await db.flush()
    view = await run_view(db, run, access="write", user=admin)
    assert view["workflow_title"] == "Story / epic delivery"
