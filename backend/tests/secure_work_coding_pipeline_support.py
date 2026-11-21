"""Shared helpers for the test_secure_work_coding_pipeline_* modules."""

from __future__ import annotations

from sqlalchemy import select

from app.models import User, WorkChangePlan, WorkItem, WorkItemChangeUnit
from app.time_utils import utc_now


def _work_item(**overrides) -> WorkItem:
    payload = {
        "source_type": "jira",
        "source_instance": "pipeline-test",
        "source_key": "OCX-333",
        "source_project_key": "OCX",
        "title": "Run governed coding pipeline",
        "source_status": "Open",
        "work_state": "intake",
        "sync_state": "imported",
    }
    payload.update(overrides)
    return WorkItem(**payload)


async def _create_config(client, auth_headers, **overrides) -> dict:
    payload = {
        "name": "Enterprise coding pipeline",
        "description": "Traceable plan-to-PR process.",
        "scope": {"risk_tags": ["runtime"]},
        "stages": [
            {"key": "intake", "label": "Intake", "required": True},
            {"key": "policy_preflight", "label": "Policy preflight", "required": True},
            {"key": "implementation", "label": "Implementation", "required": True},
            {"key": "local_validation", "label": "Local validation", "required": True},
            {"key": "acceptance_closeout", "label": "Acceptance closeout", "required": True},
        ],
        "required_stage_keys": ["intake", "policy_preflight", "implementation", "local_validation"],
        "controls": {"pause": True, "resume": True, "cancel": True},
        "review_status": "reviewed",
    }
    payload.update(overrides)
    response = await client.post("/api/v1/secure-work/coding-pipelines", headers=auth_headers, json=payload)
    assert response.status_code == 200, response.text
    return response.json()


async def _approved_plan_and_unit(db, item: WorkItem, **overrides) -> tuple[WorkChangePlan, WorkItemChangeUnit]:
    actor = (await db.execute(select(User))).scalars().first()
    assert actor is not None
    unit = WorkItemChangeUnit(
        work_item_id=item.id,
        repository_name=overrides.get("repository_name", "acme-orders-runtime"),
        branch_name=overrides.get("branch_name", f"feature/{item.source_key.lower()}-secure-run"),
        scope=overrides.get("scope", "Governed local implementation"),
        expected_paths_json=overrides.get("expected_paths", ["backend/app/services/secure_work"]),
        validation_commands_json=overrides.get(
            "validation_commands",
            ["backend/.venv/bin/python -m pytest backend/tests/test_secure_work_coding_pipeline.py"],
        ),
        reviewer_policy_json={},
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
        title=f"{item.source_key} approved secure development plan",
        understood_request=item.title,
        change_units_json=[
            {
                "id": unit.id,
                "repository_name": unit.repository_name,
                "branch_name": unit.branch_name,
                "expected_paths": list(unit.expected_paths_json or []),
                "validation_commands": list(unit.validation_commands_json or []),
            }
        ],
        planned_files_json=[
            {"repository_name": unit.repository_name, "paths": list(unit.expected_paths_json or [])}
        ],
        validation_plan_json=[
            {"command": command, "repository_name": unit.repository_name, "source": "test"}
            for command in list(unit.validation_commands_json or [])
        ],
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
