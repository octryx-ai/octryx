"""Contract: a queued Action run says why it is still waiting, as a fixed safe code.

``queue_wait_reason`` is an additive field of the run list. It carries one of the dispatcher's
closed skip reasons only while the run is still queued and its queue entry still pending; raw,
unknown or secret-like ``last_error`` text and every terminal/no-longer-waiting state give
``null``. ``last_error`` itself is never returned, and the existing fields are unchanged.
"""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.models import Project, Task, TaskQueueEntry, TaskRun, User
from app.services.admin.task._admin_task_management import list_task_runs
from app.services.admin.task._queue_wait_reason import QUEUE_WAIT_REASONS, queue_wait_reason
from tests.conftest import ADMIN_PASSWORD

DISPATCH_SOURCE = Path(__file__).resolve().parents[1] / "app" / "services" / "worker_pool" / "dispatch.py"
SECRET_LIKE = "redis://user:hunter2@cache:6379 refused; token=sk-live-123"
EXISTING_FIELDS = {
    "id",
    "task_id",
    "session_id",
    "status",
    "started_by",
    "started_at",
    "completed_at",
    "error",
    "duration_seconds",
    "steps_log",
    "queue_priority",
    "queue_status",
    "queue_required_domain",
    "queue_assigned_to",
    "queued_at",
    "queue_started_at",
    "estimated_wait_seconds",
}


def test_the_whitelist_is_exactly_the_dispatchers_skip_reasons():
    source = DISPATCH_SOURCE.read_text(encoding="utf-8")
    literal = set(re.findall(r'_decision\(\s*"skipped",\s*"([a-z_]+)"', source))
    computed = set(re.findall(r'reason = "([a-z_]+)" if not routing_rules else "([a-z_]+)"', source)[0])
    assert QUEUE_WAIT_REASONS == literal | computed


@pytest.mark.parametrize("code", sorted(QUEUE_WAIT_REASONS))
def test_a_known_code_is_returned_only_while_queued_and_pending(code):
    waiting = SimpleNamespace(status="pending", completed_at=None, last_error=code)
    assert queue_wait_reason("queued", waiting) == code
    for run_status in ("running", "success", "error", "cancelled", "skipped"):
        assert queue_wait_reason(run_status, waiting) is None, run_status
    for entry_status in ("in_progress", "completed", "failed", "dead_letter", "cancelled"):
        assert (
            queue_wait_reason("queued", SimpleNamespace(status=entry_status, completed_at=None, last_error=code))
            is None
        )
    done = SimpleNamespace(status="pending", completed_at=datetime.now(UTC), last_error=code)
    assert queue_wait_reason("queued", done) is None
    assert queue_wait_reason("queued", None) is None


@pytest.mark.parametrize(
    "raw",
    [
        SECRET_LIKE,
        "queue entry expired before assignment",
        "redis queue unavailable; using database queue",
        "No_Available_Workers",
        " no_available_workers",
        "",
        None,
        42,
        ["no_available_workers"],
    ],
)
def test_raw_or_unknown_errors_are_never_returned(raw):
    assert queue_wait_reason("queued", SimpleNamespace(status="pending", completed_at=None, last_error=raw)) is None


async def _task_with_runs(db, entries: list[tuple[str, str, object]]) -> Task:
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    project = (await db.execute(select(Project))).scalars().first()
    task = Task(dispatch_binding="task_definition", name=f"wait-reason-{uuid.uuid4().hex[:6]}", owner_id=admin.id, project_id=project.id)
    db.add(task)
    await db.flush()
    for index, (run_status, entry_status, last_error) in enumerate(entries):
        run = TaskRun(id=str(uuid.uuid4()), task_id=task.id, status=run_status, started_by=admin.id)
        db.add(run)
        await db.flush()
        db.add(
            TaskQueueEntry(
                id=str(uuid.uuid4()),
                task_run_id=run.id,
                project_id=project.id,
                task_type="agent_run",
                priority=5,
                status=entry_status,
                last_error=last_error,
                queued_at=datetime(2026, 10, 4, 10, index),
            )
        )
    await db.commit()
    return task


@pytest.mark.asyncio
async def test_the_run_list_adds_only_the_safe_reason_and_keeps_existing_fields(db):
    task = await _task_with_runs(
        db,
        [
            ("queued", "pending", "no_available_workers"),
            ("queued", "pending", SECRET_LIKE),
            ("cancelled", "pending", "no_available_workers"),
            ("success", "completed", "no_available_workers"),
        ],
    )
    runs = await list_task_runs(db, task_id=task.id)
    by_reason = sorted((run["status"], str(run["queue_wait_reason"])) for run in runs)
    assert by_reason == [
        ("cancelled", "None"),
        ("queued", "None"),
        ("queued", "no_available_workers"),
        ("success", "None"),
    ]
    for run in runs:
        assert set(run) == EXISTING_FIELDS | {"queue_wait_reason"}, "additive only"
        assert "last_error" not in run
        assert "hunter2" not in repr(run)


@pytest.mark.asyncio
async def test_the_admin_runs_endpoint_carries_the_reason_and_no_raw_error(client, db):
    task = await _task_with_runs(
        db, [("queued", "pending", "paused_due_to_rate_limit"), ("queued", "pending", SECRET_LIKE)]
    )
    login = await client.post("/admin/login", data={"username": "admin", "password": ADMIN_PASSWORD})
    assert login.status_code == 303
    response = await client.get(f"/admin/chat/api/panel/tasks/{task.id}/runs")
    assert response.status_code == 200, response.text
    reasons = sorted(str(run["queue_wait_reason"]) for run in response.json())
    assert reasons == ["None", "paused_due_to_rate_limit"]
    assert "hunter2" not in response.text and "last_error" not in response.text
