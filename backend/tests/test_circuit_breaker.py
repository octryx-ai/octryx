import uuid
from datetime import timedelta

import pytest
from sqlalchemy import select

import app.services.circuit_breaker as circuit_breaker_package
import app.tools.registry as registry_module
from app.models import CircuitBreakerState, FailedTaskRun, Project, Task, TaskRun, User
from app.services.circuit_breaker import (
    escalate_failed_task_run,
    escalate_failed_task_run_decision,
)
from app.time_utils import ensure_utc, utc_now_aware
from app.tools.context import ToolContext
from tests.conftest import ADMIN_PASSWORD


@pytest.mark.asyncio
async def test_execute_tool_with_plugins_opens_circuit_breaker_after_repeated_failures(db, monkeypatch):
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    project = (await db.execute(select(Project).where(Project.name == "acme-orders"))).scalar_one()

    async def fake_dispatch_registered_tool(_tool_name, _params, _context):
        return {"error": "jira unavailable"}

    monkeypatch.setattr(registry_module, "_dispatch_registered_tool", fake_dispatch_registered_tool)

    context = ToolContext(
        user_id=admin.id,
        project_ids=[project.id],
        roles=["admin"],
        session_id="session-1",
        project_config={"connectors": {"jira": {"enabled": True}}},
        db=db,
    )

    for _ in range(circuit_breaker_package.CIRCUIT_BREAKER_FAILURE_THRESHOLD):
        result = await registry_module.execute_tool_with_plugins(
            "search_jira_tickets",
            {"jql": "project = RIVER"},
            context,
        )
        assert result["error"] == "jira unavailable"

    # Keyed per connection scope: the Workspace inherits the platform connection.
    breaker = await db.get(CircuitBreakerState, "jira@platform")
    assert breaker is not None
    assert breaker.state == "open"
    blocked = await registry_module.execute_tool_with_plugins("search_jira_tickets", {"jql": "project = RIVER"}, context)
    assert blocked["circuit_breaker_state"] == "open"
    assert "Circuit breaker is open" in blocked["error"]


@pytest.mark.asyncio
async def test_failed_task_run_backoff_escalates_to_dead_letter(db):
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    project = (await db.execute(select(Project).where(Project.name == "acme-orders"))).scalar_one()

    task = Task(dispatch_binding="task_definition",
        id=str(uuid.uuid4()),
        project_id=project.id,
        name="Retry task",
        description="test",
        task_type="agent_run",
        agent_type="change",
        is_active=True,
        owner_id=admin.id,
    )
    db.add(task)
    await db.flush()

    first_run = TaskRun(id=str(uuid.uuid4()), task_id=task.id, status="error", started_by=admin.id, input_={})
    db.add(first_run)
    await db.flush()

    row, delay = await escalate_failed_task_run(
        db,
        task_id=task.id,
        task_run_id=first_run.id,
        error="first failure",
        trigger_id=None,
    )
    assert row.status == "pending_retry"
    assert delay == 0

    expected_delays = [1, 4, 16]
    current_id = row.id
    for idx, expected in enumerate(expected_delays, start=2):
        retry_run = TaskRun(id=str(uuid.uuid4()), task_id=task.id, status="error", started_by=admin.id, input_={})
        db.add(retry_run)
        await db.flush()
        row, delay = await escalate_failed_task_run(
            db,
            task_id=task.id,
            task_run_id=retry_run.id,
            error=f"failure {idx}",
            trigger_id=current_id,
        )
        assert row.retry_count == idx
        assert row.status == "pending_retry"
        assert delay == expected
        assert ensure_utc(row.next_retry_at) >= utc_now_aware() + timedelta(seconds=expected - 1)

    final_run = TaskRun(id=str(uuid.uuid4()), task_id=task.id, status="error", started_by=admin.id, input_={})
    db.add(final_run)
    await db.flush()
    row, delay = await escalate_failed_task_run(
        db,
        task_id=task.id,
        task_run_id=final_run.id,
        error="failure 5",
        trigger_id=current_id,
    )
    assert row.retry_count == 5
    assert row.status == "dead_letter"
    assert delay is None


@pytest.mark.asyncio
async def test_failed_task_run_decision_marks_retryable_and_terminal_outcomes(db):
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    project = (await db.execute(select(Project).where(Project.name == "acme-orders"))).scalar_one()

    task = Task(dispatch_binding="task_definition",
        id=str(uuid.uuid4()),
        project_id=project.id,
        name="Decision retry task",
        description="test",
        task_type="agent_run",
        agent_type="change",
        is_active=True,
        owner_id=admin.id,
    )
    db.add(task)
    await db.flush()

    first_run = TaskRun(id=str(uuid.uuid4()), task_id=task.id, status="error", started_by=admin.id, input_={})
    db.add(first_run)
    await db.flush()

    row, decision = await escalate_failed_task_run_decision(
        db,
        task_id=task.id,
        task_run_id=first_run.id,
        error="provider failed with Bearer secret-token",
        trigger_id=None,
    )
    payload = decision.as_dict()
    assert payload["status"] == "pending_retry"
    assert payload["retryable"] is True
    assert payload["terminal"] is False
    assert payload["retry_delay_seconds"] == 0
    assert payload["queue_status"] == "retry_pending"
    assert payload["reason"] == "retry_scheduled"
    assert payload["failure_message"] == "provider failed with Bearer [redacted]"

    current_id = row.id
    for idx in range(2, 6):
        retry_run = TaskRun(id=str(uuid.uuid4()), task_id=task.id, status="error", started_by=admin.id, input_={})
        db.add(retry_run)
        await db.flush()
        row, decision = await escalate_failed_task_run_decision(
            db,
            task_id=task.id,
            task_run_id=retry_run.id,
            error=f"failure {idx}",
            trigger_id=current_id,
        )

    terminal_payload = decision.as_dict()
    assert row.status == "dead_letter"
    assert terminal_payload["retryable"] is False
    assert terminal_payload["terminal"] is True
    assert terminal_payload["retry_delay_seconds"] is None
    assert terminal_payload["queue_status"] == "dead_letter"
    assert terminal_payload["reason"] == "retry_policy_exhausted"


@pytest.mark.asyncio
async def test_admin_circuit_breakers_endpoint_lists_breakers_and_failed_runs(client, db):
    login_resp = await client.post("/admin/login", data={"username": "admin", "password": ADMIN_PASSWORD})
    assert login_resp.status_code == 303

    db.add(
        CircuitBreakerState(
            connector_name="jira",
            state="open",
            failure_count=4,
            last_error="jira down",
        )
    )
    db.add(
        FailedTaskRun(
            id=str(uuid.uuid4()),
            task_id="task-1",
            task_run_id="run-1",
            retry_count=4,
            last_error="boom",
            status="dead_letter",
        )
    )
    await db.commit()

    resp = await client.get("/admin/circuit-breakers")
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["circuit_breakers"][0]["connector_name"] == "jira"
    assert payload["failed_task_runs"][0]["status"] == "dead_letter"
    assert payload["failed_task_runs"][0]["terminal"] is True
    assert payload["failed_task_runs"][0]["decision"]["reason"] == "retry_policy_exhausted"
