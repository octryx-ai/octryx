"""Shared actor, Work item and approved plan seeding for the secure work coding execution tests."""

from __future__ import annotations

from sqlalchemy import select

from app.models import User, WorkChangePlan, WorkItem, WorkItemChangeUnit
from app.time_utils import utc_now


async def _actor(db) -> User:
    return (await db.execute(select(User).where(User.username == "admin"))).scalar_one()


async def _work_item(db, *, source_key: str = "ACME-615") -> WorkItem:
    item = WorkItem(
        source_type="jira",
        source_instance="risk",
        source_key=source_key,
        source_project_key="ACME",
        source_url=f"https://jira.example.test/browse/{source_key}",
        title="Cleaning Terraform and Helm Config",
        description="Clean Terraform removed blocks and prod/non-prod config after the pipeline split.",
        issue_type="Task",
        source_status="Open",
        work_state="ready_for_implementation",
        sync_state="imported",
        labels_json=["octryx"],
    )
    db.add(item)
    await db.flush()
    return item


async def _approved_plan_and_unit(
    db,
    actor: User,
    item: WorkItem,
) -> tuple[WorkChangePlan, WorkItemChangeUnit]:
    unit = WorkItemChangeUnit(
        work_item_id=item.id,
        repository_name="aws-shop-infrastructure",
        branch_name="feature/ACME-615-clean-base-terraform-leftovers",
        scope="Clean approved Terraform and Helm base configuration leftovers.",
        expected_paths_json=["terraform/base", "helm"],
        validation_commands_json=["terraform validate", "helm lint"],
        reviewer_policy_json={"required_reviewers": ["vetodoro"]},
        status="planned",
        created_by=actor.id,
    )
    db.add(unit)
    await db.flush()
    now = utc_now()
    plan = WorkChangePlan(
        work_item_id=item.id,
        version=1,
        status="approved",
        title="ACME-615 approved coding plan",
        understood_request="Clean Terraform removed blocks and prod/non-prod config after pipeline split.",
        change_units_json=[
            {
                "id": unit.id,
                "repository_name": unit.repository_name,
                "branch_name": unit.branch_name,
                "expected_paths": list(unit.expected_paths_json or []),
            }
        ],
        planned_files_json=[{"repository_name": unit.repository_name, "paths": ["terraform/base", "helm"]}],
        validation_plan_json=[{"command": "terraform validate"}, {"command": "helm lint"}],
        required_approvals_json=[{"type": "work_plan", "required": True}],
        rollback_plan="Close or revert the resulting PR.",
        evidence_json={"source": "unit-test"},
        created_by=actor.id,
        updated_by=actor.id,
        approved_by=actor.id,
        decided_by=actor.id,
        approved_at=now,
        decided_at=now,
    )
    db.add(plan)
    await db.flush()
    return plan, unit
