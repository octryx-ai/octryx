"""Contract: a design-sync task is created only for a schedulable cron."""

from __future__ import annotations

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select

from app import runtime_lifecycle
from app.models import Project, Task, TaskStep, User
from app.models.project.scheduler import Scheduler
from app.services.design_delivery_sync import create_design_trace_sync_workflow_task
from tests.conftest import ADMIN_PASSWORD

pytestmark = pytest.mark.asyncio
WORKFLOW = "releases"
INVALID = {
    "0 9 * * 7": "cron_field_invalid",
    "0 9 30 2 *": "cron_never_fires",
    "0 " * 51: "cron_too_long",
}


class _RegistrationRecorder:
    def __init__(self) -> None:
        self.reconciles = 0

    def request_reconcile(self) -> None:
        self.reconciles += 1

    def __getattr__(self, name):
        raise AssertionError(f"no scheduler call other than registration is expected: {name}")


@pytest.fixture
def registration(monkeypatch) -> _RegistrationRecorder:
    recorder = _RegistrationRecorder()
    monkeypatch.setattr(runtime_lifecycle, "get_task_scheduler", lambda: recorder)
    return recorder


async def _ids(db) -> tuple[str, str]:
    project = (await db.execute(select(Project).where(Project.name == "demo"))).scalar_one()
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    return project.id, admin.id


async def _counts(db) -> tuple[int, int, int]:
    # A fresh transaction: what a later request (or a retry) would actually find.
    await db.rollback()
    return tuple(
        [(await db.execute(select(func.count(model.id)))).scalar_one() for model in (Task, TaskStep, Scheduler)]
    )


async def test_unschedulable_cron_is_refused_before_any_task_step_or_scheduler(db, registration):
    project_id, user_id = await _ids(db)
    before = await _counts(db)
    for cron, code in INVALID.items():
        with pytest.raises(HTTPException) as refused:
            await create_design_trace_sync_workflow_task(
                db,
                project_id=project_id,
                workflow_id=WORKFLOW,
                user_id=user_id,
                payload={"cron_expression": cron, "task_name": f"Invalid {code}"},
            )
        assert refused.value.status_code == 422
        assert refused.value.detail["code"] == code and refused.value.detail["field"] == "cron_expression"
        assert await _counts(db) == before, f"no orphan rows for {cron!r}"
        await db.commit()
        assert await _counts(db) == before, "still none after a later commit"
    assert registration.reconciles == 0, "nothing was registered"


async def test_the_route_returns_the_typed_422_and_writes_nothing(client, db, registration):
    project_id, _ = await _ids(db)
    assert (
        await client.post("/admin/login", data={"username": "admin", "password": ADMIN_PASSWORD})
    ).status_code == 303
    before = await _counts(db)
    response = await client.post(
        f"/admin/chat/api/panel/projects/{project_id}/design-trace-sync-workflows/{WORKFLOW}/create-task",
        json={"cron_expression": "0 9 30 2 *", "task_name": "Route probe"},
    )
    assert response.status_code == 422, response.text
    assert response.json()["detail"]["code"] == "cron_never_fires"
    assert await _counts(db) == before
    assert registration.reconciles == 0


@pytest.mark.parametrize("cron, stored", [("0 * * * *", "0 * * * *"), ("  0 0 29 2 mon  ", "0 0 29 2 mon")])
async def test_schedulable_cron_keeps_the_success_payload(db, registration, cron, stored):
    project_id, user_id = await _ids(db)
    tasks, steps, schedulers = await _counts(db)
    created = await create_design_trace_sync_workflow_task(
        db,
        project_id=project_id,
        workflow_id=WORKFLOW,
        user_id=user_id,
        payload={"cron_expression": cron, "task_name": "Trace Sync PRs", "limit_per_repository": 12},
    )
    assert set(created) == {"project_id", "workflow", "task", "scheduler"}
    assert created["task"]["name"] == "Trace Sync PRs"
    assert created["scheduler"]["cron_expression"] == stored, "the same normalized string is validated and stored"
    assert await _counts(db) == (tasks + 1, steps + 2, schedulers + 1)
    assert registration.reconciles == 1, "registered once, never executed"


async def test_missing_input_and_lookup_errors_keep_their_existing_semantics(db, registration):
    project_id, user_id = await _ids(db)
    before = await _counts(db)
    cases = [
        (project_id, WORKFLOW, {}, "cron_expression is required"),
        (project_id, WORKFLOW, {"cron_expression": "   "}, "cron_expression is required"),
        ("no-such-project", WORKFLOW, {"cron_expression": "0 9 30 2 *"}, "Project not found"),
        (project_id, "no-such-workflow", {"cron_expression": "0 9 30 2 *"}, "Trace sync workflow not found"),
    ]
    for project, workflow, payload, message in cases:
        with pytest.raises(ValueError, match=message):
            await create_design_trace_sync_workflow_task(
                db, project_id=project, workflow_id=workflow, user_id=user_id, payload=payload
            )
    assert await _counts(db) == before
    assert registration.reconciles == 0
