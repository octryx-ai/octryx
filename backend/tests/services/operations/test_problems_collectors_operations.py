"""The intake, run, rule denial, token and device collectors: failed, blocked and offline states become problems or attention, healthy ones nothing."""

from __future__ import annotations

from datetime import timedelta

import pytest

from app.models import (
    DeviceJob,
    PolicyDecisionLog,
    Session,
    StoredSecret,
    Task,
    TaskRun,
    UserDevice,
    WorkflowRun,
    WorkItemSyncConfig,
    WorkItemSyncRun,
)
from app.services.decisions.recorder import build_gate_record
from app.services.problems import denials, devices, intake, runs, tokens
from tests.services.operations.problems_collectors_support import NOW, _by_object, _setup, uid


@pytest.mark.asyncio
async def test_intake_failed_blocked_and_completed(db):
    project, admin, ctx = await _setup(db)
    configs = {status: WorkItemSyncConfig(id=uid(), name=f"Intake {status}", project_id=project.id,
                                          created_by=admin.id, last_sync_status=status, last_sync_at=NOW)
               for status in ("failed", "blocked", "completed")}
    db.add_all(configs.values())
    await db.flush()
    for hours, status in ((4, "completed"), (2, "failed"), (1, "failed")):
        db.add(WorkItemSyncRun(sync_config_id=configs["failed"].id, triggered_by=admin.id, status=status,
                               error="jira_auth" if status == "failed" else None,
                               created_at=NOW - timedelta(hours=hours)))
    await db.flush()

    problems = await intake.collect(db, ctx)

    failed = _by_object(problems, configs["failed"].id)[0]
    assert (failed.severity, failed.count) == ("problem", 2) and "jira auth" in failed.title
    assert "work_view=intake" in failed.fix["href"]
    assert _by_object(problems, configs["blocked"].id)[0].severity == "attention"
    assert not _by_object(problems, configs["completed"].id)


@pytest.mark.asyncio
async def test_workflow_runs_and_task_runs(db):
    project, admin, ctx = await _setup(db)

    def run(status: str, age: timedelta, **extra) -> WorkflowRun:
        return WorkflowRun(id=uid(), project_id=project.id, workflow_kind="steps", workflow_key=f"wf-{status}",
                           title=f"Run {status}", status=status, requested_by=admin.id, updated_at=NOW - age, **extra)

    paused = run("paused", timedelta(days=20), pause_reason="loop_limit")
    failed = run("failed", timedelta(hours=2), last_error="boom")
    old_failure = run("failed", timedelta(days=9))
    waiting = run("waiting", timedelta(hours=30), waiting_kind="awaiting_approval")
    fresh_wait = run("waiting", timedelta(hours=2), waiting_kind="awaiting_approval")
    child_wait = run("waiting", timedelta(hours=30), waiting_kind="sub_workflow")
    done = run("completed", timedelta(hours=1))
    task = Task(dispatch_binding="task_definition", id=uid(), project_id=project.id, name="Nightly report", task_type="agent_run", owner_id=admin.id)
    db.add_all([paused, failed, old_failure, waiting, fresh_wait, child_wait, done, task])
    await db.flush()
    # "success" is what the scheduler writes for a good run (read as a failure, it reports false "failed runs").
    for hours, status in ((5, "failed"), (4, "success"), (2, "failed"), (1, "error")):
        db.add(TaskRun(task_id=task.id, status=status, started_by=admin.id, started_at=NOW - timedelta(hours=hours)))
    await db.flush()

    problems = await runs.collect(db, ctx)

    assert _by_object(problems, paused.id)[0].reason_code == "paused"
    assert "loop limit" in _by_object(problems, paused.id)[0].title
    assert _by_object(problems, failed.id)[0].severity == "problem"
    assert _by_object(problems, waiting.id)[0].severity == "attention"
    assert not any(_by_object(problems, item.id) for item in (old_failure, fresh_wait, child_wait, done))
    task_problem = _by_object(problems, task.id)[0]
    assert (task_problem.count, task_problem.since) == (2, NOW - timedelta(hours=2))


@pytest.mark.asyncio
async def test_rule_denials_are_grouped_per_workspace_and_rule(db):
    project, _, ctx = await _setup(db)
    for minutes, rule, outcome in ((30, "deny-shell", "denied"), (10, "deny-shell", "denied"),
                                   (5, "deny-shell", "needs_approval"), (5, "deny-web", "denied")):
        db.add(PolicyDecisionLog(**build_gate_record(
            gate="tool_policy", outcome=outcome, action="call_tool", resource="shell", workspace_id=project.id,
            rule=rule, run_key="r1", created_at=NOW - timedelta(minutes=minutes))))
    db.add(PolicyDecisionLog(**build_gate_record(
        gate="tool_policy", outcome="denied", action="call_tool", resource="x", workspace_id=project.id,
        rule="deny-shell", run_key="r1", created_at=NOW - timedelta(days=8))))
    await db.flush()

    problems = await denials.collect(db, ctx)

    shell = _by_object(problems, "deny-shell")[0]
    assert (shell.severity, shell.count, shell.since) == ("attention", 2, NOW - timedelta(minutes=30))
    assert shell.key == f"rule_denial:deny-shell@{project.id}:denied"
    assert "policy=deny-shell" in shell.fix["href"] and "tab=observabilityDecisions" in shell.fix["href"]
    assert _by_object(problems, "deny-web")[0].count == 1


@pytest.mark.asyncio
async def test_tokens_expired_soon_and_later(db):
    project, _, ctx = await _setup(db)
    expired, soon, later = (StoredSecret(id=uid(), name=name, secret_type="api_key", project_id=project.id,
                                         tool_name="jira", expires_at=NOW + delta)
                            for name, delta in (("old", timedelta(days=-1)), ("soon", timedelta(days=3)),
                                                ("later", timedelta(days=60))))
    db.add_all([expired, soon, later])
    await db.flush()

    problems = await tokens.collect(db, ctx)

    assert _by_object(problems, expired.id)[0].severity == "problem"
    assert _by_object(problems, soon.id)[0].reason_code == "expires_soon"
    assert not _by_object(problems, later.id)


@pytest.mark.asyncio
async def test_devices_offline_with_waiting_work_failed_jobs_and_healthy(db):
    project, admin, ctx = await _setup(db)
    chat = Session(id=uid(), user_id=admin.id, agent_type="diagnosis", status="active", metadata_={})

    def device(name: str, **extra) -> UserDevice:
        return UserDevice(owner_user_id=admin.id, name=name, name_key=name.lower(), os="macos", public_key="k",
                          **extra)

    offline = device("Laptop", last_seen_at=NOW - timedelta(hours=2))
    online = device("Desk", last_seen_at=NOW)
    db.add_all([chat, offline, online])
    await db.flush()
    for target, status in ((offline, "offered"), (online, "running"), (online, "failed")):
        db.add(DeviceJob(device_id=target.id, owner_user_id=admin.id, session_id=chat.id, workspace_id=project.id,
                         folder="/w", profile="read", status=status, updated_at=NOW - timedelta(minutes=5)))
    await db.flush()

    problems = await devices.collect(db, ctx)

    laptop = _by_object(problems, offline.id)
    assert [(item.severity, item.reason_code) for item in laptop] == [("problem", "offline")]
    assert [(item.severity, item.reason_code) for item in _by_object(problems, online.id)] == [
        ("attention", "jobs_failed")]
    assert laptop[0].fix["href"] == "/chat?area=personal&tab=devices"
