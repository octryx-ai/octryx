"""A failed package import keeps its typed error and commits one failed audit row.

The import's failure branches roll the attempt back and then write a failed ``ImportLog``. A
rollback expires every persisted row the session holds, so the audit row must be built from values
captured before it. These tests run the real routes and service on committed sessions (no rollback
or exception-branch stubs) and read the evidence back from a fresh session.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models import ExportPackage, ImportLog, Project, Task, TaskStep, User
from app.services.error_facts import error_text
from app.services.export_package.core import checksum_for_content
from app.services.export_package.importing import import_package
from app.services.export_package.service import create_export_package

pytestmark = pytest.mark.committed_db


@pytest.fixture
def fresh(db):
    """Independent sessions on the committed test database (the request's own session is separate)."""
    return async_sessionmaker(db.bind, class_=AsyncSession, expire_on_commit=False)


def _inline(entity: dict) -> tuple[dict, str]:
    content = {"format_version": 1, "package_type": "task",
               "entity": {"agent_type": "diagnosis", "config": {}, "dispatch_binding": "task_definition", **entity}}
    return {"package_type": "task", "content_json": content}, checksum_for_content(content)


async def _admin_and_project(db) -> tuple[str, str]:
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    project = (await db.execute(select(Project).where(Project.name == "acme-orders"))).scalar_one()
    return admin.id, project.id


async def _evidence(fresh_factory, checksum: str, task_name: str) -> tuple[list[ImportLog], int, int]:
    """Committed state only: a fresh session, after the request's own session is gone."""
    async with fresh_factory() as fresh:
        logs = list(
            (await fresh.execute(select(ImportLog).where(ImportLog.package_checksum == checksum))).scalars()
        )
        task_ids = list((await fresh.execute(select(Task.id).where(Task.name == task_name))).scalars())
        steps = 0
        if task_ids:
            steps = (
                await fresh.execute(select(func.count()).select_from(TaskStep).where(TaskStep.task_id.in_(task_ids)))
            ).scalar_one()
        return logs, len(task_ids), steps


async def test_api_duplicate_keeps_409_and_commits_one_failed_audit(client, auth_headers, db, fresh):
    admin_id, project_id = await _admin_and_project(db)
    name = f"audit-dup-{uuid.uuid4().hex[:6]}"
    db.add(Task(dispatch_binding="task_definition", id=str(uuid.uuid4()), project_id=project_id, name=name, agent_type="diagnosis", config={},
                owner_id=admin_id))
    await db.commit()
    package, checksum = _inline({"name": name})

    resp = await client.post("/api/v1/packages/import", headers=auth_headers,
                             json={"package_json": package, "target_project_id": project_id})

    assert resp.status_code == 409
    assert resp.json()["detail"] == f"Task '{name}' already exists in target project"
    logs, tasks, _ = await _evidence(fresh, checksum, name)
    assert len(logs) == 1
    log = logs[0]
    assert (log.status, log.imported_by, log.package_id, log.target_project_id) == (
        "failed", admin_id, None, project_id)
    assert log.errors == [f"Task '{name}' already exists in target project"]
    assert tasks == 1  # only the pre-existing task


async def test_panel_stored_package_keeps_422_and_records_the_saved_package(client, auth_headers, db, fresh):
    admin_id, project_id = await _admin_and_project(db)
    source_name = f"audit-legacy-{uuid.uuid4().hex[:6]}"
    # A stored Task with a never-firing schedule (the panel refuses it on save, 422).
    legacy = Task(dispatch_binding="task_definition", id=str(uuid.uuid4()), project_id=project_id, name=source_name, agent_type="diagnosis",
                  schedule="0 0 31 4 *", config={}, owner_id=admin_id)
    db.add(legacy)
    await db.commit()
    admin = await db.get(User, admin_id)
    stored = await create_export_package(db, current_user=admin, package_type="task", entity_id=legacy.id)
    target_name = f"{source_name}-copy"

    resp = await client.post("/admin/chat/api/panel/import-packages", headers=auth_headers,
                             json={"package_id": stored["id"], "target_project_id": project_id,
                                   "name_override": target_name})

    assert resp.status_code == 422
    detail = resp.json()["detail"]
    assert (detail["code"], detail["field"]) == ("cron_never_fires", "schedule")
    async with fresh() as session:
        row = await session.get(ExportPackage, stored["id"])
        checksum = row.checksum
    logs, tasks, _ = await _evidence(fresh, checksum, target_name)
    assert len(logs) == 1
    assert (logs[0].status, logs[0].imported_by, logs[0].package_id) == ("failed", admin_id, stored["id"])
    assert logs[0].errors == [str(detail)]
    assert tasks == 0


async def test_failure_after_a_tentative_task_write_rolls_back_and_keeps_a_sanitized_audit(db, fresh):
    admin_id, project_id = await _admin_and_project(db)
    name = f"audit-steps-{uuid.uuid4().hex[:6]}"
    # The task row is flushed first; the step position then fails while the steps are built.
    package, checksum = _inline({"name": name, "steps": [{"name": "Step", "position": "secret-not-a-number"}]})

    async with fresh() as session:
        actor = await session.get(User, admin_id)
        with pytest.raises(ValueError):
            await import_package(session, current_user=actor, package_json=package, target_project_id=project_id)

    logs, tasks, steps = await _evidence(fresh, checksum, name)
    assert (tasks, steps) == (0, 0)
    assert len(logs) == 1
    assert (logs[0].status, logs[0].imported_by) == ("failed", admin_id)
    assert logs[0].errors == [error_text("package_import_failed", ValueError())]
    assert "secret-not-a-number" not in str(logs[0].errors)


async def test_successful_import_is_unchanged(client, auth_headers, db, fresh):
    _, project_id = await _admin_and_project(db)
    name = f"audit-ok-{uuid.uuid4().hex[:6]}"
    package, checksum = _inline({"name": name, "schedule": "0 9 * * 0", "steps": [{"name": "Step", "position": 1}]})

    resp = await client.post("/api/v1/packages/import", headers=auth_headers,
                             json={"package_json": package, "target_project_id": project_id})

    assert resp.status_code == 200, resp.text
    logs, tasks, steps = await _evidence(fresh, checksum, name)
    assert (tasks, steps) == (1, 1)
    assert len(logs) == 1
    assert logs[0].status == "completed"
    assert logs[0].imported_entity_name == name


async def test_an_import_without_a_dispatch_binding_is_refused_before_any_task_write(client, auth_headers, db, fresh):
    _, project_id = await _admin_and_project(db)
    name = f"audit-unbound-{uuid.uuid4().hex[:6]}"
    package, checksum = _inline({"name": name, "dispatch_binding": None})

    resp = await client.post("/api/v1/packages/import", headers=auth_headers,
                             json={"package_json": package, "target_project_id": project_id})

    assert resp.status_code == 422
    assert "dispatch_binding_invalid" in resp.text
    _logs, tasks, _steps = await _evidence(fresh, checksum, name)
    assert tasks == 0
