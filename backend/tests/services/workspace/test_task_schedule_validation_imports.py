"""Package and data imports refuse an unschedulable value without persisting anything and keep their trimming and removal contracts."""

from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.models import Task
from app.services.data_transfer.import_rows import _import_task_rows
from app.services.export_package.importing import import_package
from app.services.export_package.upsert_task import upsert_task_from_package
from tests.support.task_schedule_validation_support import _admin, _detail, _project, _task_count

# --- package and data import -------------------------------------------------------------------


def _task_package(name: str, **entity) -> dict:
    return {
        "package_type": "task",
        "content_json": {"format_version": 1, "package_type": "task",
                         "entity": {"name": name, "agent_type": "diagnosis", "config": {},
                                    "dispatch_binding": "task_definition", **entity}},
    }


@pytest.mark.asyncio
async def test_import_overwrite_refused_without_touching_the_existing_task(db):
    admin, project = await _admin(db), await _project(db)
    existing = Task(dispatch_binding="task_definition", id=str(uuid.uuid4()), project_id=project.id, name="w6-existing", description="before",
                    agent_type="diagnosis", schedule="0 9 * * 0", config={}, owner_id=admin.id)
    db.add(existing)
    await db.commit()

    # The package writer itself (both import entry points call it). `import_package`'s own failure branch
    # is exercised separately.
    with pytest.raises(HTTPException) as exc:
        await upsert_task_from_package(
            db, current_user=admin, overwrite_existing=True, name_override=None, target_project_id=project.id,
            entity={"name": "w6-existing", "description": "after", "agent_type": "diagnosis", "config": {},
                    "schedule": "0 0 31 4 *"},
        )
    assert _detail(exc)["code"] == "cron_never_fires"
    # Not even mutated in the session: the refusal comes before any field changes.
    assert (existing.description, existing.schedule) == ("before", "0 9 * * 0")
    assert existing not in db.dirty


@pytest.mark.asyncio
@pytest.mark.parametrize(("entity", "stored"), [({"schedule": "5 4 1,15 * 6"}, "5 4 1,15 * 6"), ({}, None),
                                                 ({"schedule": None}, None), ({"schedule": ""}, "")])
async def test_package_import_keeps_valid_and_removal_values(db, entity, stored):
    admin, project = await _admin(db), await _project(db)
    name = f"w6-ok-{uuid.uuid4().hex[:6]}"
    await import_package(db, current_user=admin, target_project_id=project.id, package_json=_task_package(name, **entity))
    task = (await db.execute(select(Task).where(Task.name == name))).scalar_one()
    assert task.schedule == stored


@pytest.mark.asyncio
async def test_data_import_fails_only_the_refused_row(db):
    admin, project = await _admin(db), await _project(db)
    rows = [
        {"name": "w6-row-bad", "agent_type": "diagnosis", "schedule": 15, "dispatch_binding": "task_definition"},
        {"name": "w6-row-good", "agent_type": "diagnosis", "schedule": "0 9 * * 0",
         "dispatch_binding": "task_definition"},
    ]
    success, failed, errors = await _import_task_rows(
        db, current_user=admin, rows=rows, target_project_id=project.id, overwrite_existing=False
    )
    assert (success, failed) == (1, 1)
    assert errors and errors[0].startswith("row 1:")
    assert await _task_count(db, "w6-row-bad") == 0
    assert await _task_count(db, "w6-row-good") == 1
