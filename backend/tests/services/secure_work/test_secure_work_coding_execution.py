"""Starting a Work item's coding execution is a workflow run for the item (the bug or the delivery workflow); a
stale plan blocks it, and the runtime control inventory stays explicit."""

from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import select

from app.models import (
    AuditLog,
    Project,
    WorkflowRun,
)
from app.services.secure_work.coding.coding_execution import start_work_item_coding_agent_execution
from tests.scripted_pool_support import scripted_pool  # noqa: F401 - fixture
from tests.secure_work_coding_execution_support import _actor, _approved_plan_and_unit, _work_item

pytestmark = pytest.mark.usefixtures("scripted_pool")


async def test_start_work_item_coding_agent_execution_blocks_stale_plan_without_agent(db):
    actor = await _actor(db)
    item = await _work_item(db, source_key="ACME-616")
    plan, unit = await _approved_plan_and_unit(db, actor, item)
    item.last_source_updated_at = plan.approved_at + timedelta(minutes=3)
    result = await start_work_item_coding_agent_execution(
        db,
        work_item_id=item.id,
        current_user=actor,
        payload={"change_plan_id": plan.id, "change_unit_ids": [unit.id]},
    )

    assert result["status"] == "blocked"
    assert result["session"] is None
    assert result["work_url"] == f"/chat?area=work&work_item_id={item.id}"
    assert result["coding_url"] == f"/chat?area=coding&work_item_id={item.id}"
    assert result["next_actions"][0]["key"] == "open_work_item"
    assert result["blockers"][0]["code"] == "source_changed_after_plan"
    assert (await db.execute(select(WorkflowRun).where(WorkflowRun.work_item_id == item.id))).first() is None
    await db.refresh(item)
    assert item.work_state == "needs_replan"
    audit = (
        await db.execute(
            select(AuditLog).where(
                AuditLog.action == "secure_work.coding_agent_execution_blocked",
                AuditLog.resource_id == item.id,
            )
        )
    ).scalar_one()
    assert audit.details["blockers"][0]["code"] == "source_changed_after_plan"


@pytest.mark.asyncio
@pytest.mark.parametrize(("issue_type", "workflow_key"), [("Bug", "bug-fix-reproduction"), ("Task", "epic-delivery")])
async def test_an_approved_plan_starts_the_items_workflow_run(db, issue_type, workflow_key):
    from app.services.workflow_runs.seeding import seed_phased_workflows

    actor = await _actor(db)
    await seed_phased_workflows(db, admin_user=actor)
    item = await _work_item(db, source_key=f"ACME-7{len(issue_type)}")
    item.issue_type = issue_type
    item.project_id = (await db.execute(select(Project).where(Project.name == "acme-orders"))).scalar_one().id
    plan, unit = await _approved_plan_and_unit(db, actor, item)

    result = await start_work_item_coding_agent_execution(
        db, work_item_id=item.id, current_user=actor, payload={"change_plan_id": plan.id, "change_unit_ids": [unit.id]})

    assert result["status"] == "started" and result["workflow_run"]["workflow_key"] == workflow_key
    run = await db.get(WorkflowRun, result["workflow_run"]["id"])
    assert (run.work_item_id, run.context["work_change_plan_id"]) == (item.id, plan.id)
    assert result["session"]["chat_url"] == f"/chat?session_id={result['session']['id']}"
