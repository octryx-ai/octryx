"""V2 node checkpoints, resuming interrupted flows and recovering stale flow runs."""

from datetime import timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.agent.orchestrator_agent import OrchestratorAgentRun
from app.models.runtime.audit import AuditLog
from app.models.runtime.flow_definition import FlowNodeRun
from app.services.flow_orchestration.dag.interrupted import recover_stale_v2_flow_runs, resume_interrupted_v2_flow_dag
from app.services.flow_orchestration.runner import execute_flow_version
from app.time_utils import utc_now
from tests.flow_orchestration_runner_support import _make_v2_flow_version


@pytest.mark.committed_db
@pytest.mark.asyncio
async def test_execute_v2_flow_commits_node_checkpoint_before_long_tool_finishes(db, monkeypatch):
    session_factory = async_sessionmaker(bind=db.bind, class_=AsyncSession, expire_on_commit=False)
    checkpoint_statuses: list[tuple[str, str]] = []

    async def fake_execute_tool(tool_name, params, context):
        async with session_factory() as inspect_db:
            rows = (
                (
                    await inspect_db.execute(
                        select(FlowNodeRun).order_by(FlowNodeRun.created_at.asc(), FlowNodeRun.node_id.asc())
                    )
                )
                .scalars()
                .all()
            )
            checkpoint_statuses.extend((row.node_id, row.status) for row in rows)
        return {"value": params["value"], "results": [{"id": "visible-checkpoint"}]}

    monkeypatch.setattr("app.services.flow_orchestration.dag.tool_node.execute_tool_with_plugins", fake_execute_tool)
    version = _make_v2_flow_version(
        db,
        "v2-durable-checkpoint",
        "f-v2-durable-checkpoint",
        "v2-durable-checkpoint",
        [
            {"id": "input", "type": "trigger"},
            {"id": "tool", "type": "tool_step", "config": {"tool": "slow_tool", "arguments": {"value": 42}}},
            {"id": "out", "type": "output"},
        ],
        [
            {"source_node_id": "input", "target_node_id": "tool"},
            {"source_node_id": "tool", "target_node_id": "out"},
        ],
    )

    run = await execute_flow_version(db, flow_version_id=version.id, user_id="tester", initial_input={"request": "go"})

    assert run.status == "completed"
    assert ("input", "completed") in checkpoint_statuses
    assert ("tool", "running") in checkpoint_statuses
    assert run.routing_policy_json["runtime"]["progress"]["phase"] == "completed"


@pytest.mark.asyncio
async def test_resume_interrupted_v2_flow_retries_only_interrupted_node(db, monkeypatch):
    class SimulatedCrash(BaseException):
        pass

    calls: list[str] = []
    crashed = False

    async def fake_execute_tool(tool_name, params, context):
        nonlocal crashed
        calls.append(tool_name)
        if tool_name == "second_tool" and not crashed:
            crashed = True
            raise SimulatedCrash("process interrupted while second tool was running")
        return {"value": tool_name, "params": params}

    monkeypatch.setattr("app.services.flow_orchestration.dag.tool_node.execute_tool_with_plugins", fake_execute_tool)
    version = _make_v2_flow_version(
        db,
        "v2-interrupted-resume",
        "f-v2-interrupted-resume",
        "v2-interrupted-resume",
        [
            {"id": "input", "type": "trigger"},
            {"id": "first", "type": "tool_step", "config": {"tool": "first_tool", "arguments": {"step": 1}}},
            {"id": "second", "type": "tool_step", "config": {"tool": "second_tool", "arguments": {"from": "{result.value}"}}},
            {"id": "out", "type": "output"},
        ],
        [
            {"source_node_id": "input", "target_node_id": "first"},
            {"source_node_id": "first", "target_node_id": "second"},
            {"source_node_id": "second", "target_node_id": "out", "source_field": "result.value", "target_field": "value"},
        ],
    )

    with pytest.raises(SimulatedCrash):
        await execute_flow_version(db, flow_version_id=version.id, user_id="tester", initial_input={"request": "go"})

    runs_before = (await db.execute(select(FlowNodeRun).order_by(FlowNodeRun.created_at.asc()))).scalars().all()
    run_id = runs_before[0].orchestrator_run_id
    assert [(item.node_id, item.status, item.attempt) for item in runs_before] == [
        ("input", "completed", 1),
        ("first", "completed", 1),
        ("second", "running", 1),
    ]
    assert calls == ["first_tool", "second_tool"]

    resumed = await resume_interrupted_v2_flow_dag(
        db,
        run_id=run_id,
        user_id="tester",
        reason="worker restart test",
    )
    runs_after = (await db.execute(select(FlowNodeRun).order_by(FlowNodeRun.created_at.asc()))).scalars().all()
    status_by_node_attempt = {(item.node_id, item.attempt): item.status for item in runs_after}
    audit_actions = {row.action for row in (await db.execute(select(AuditLog))).scalars().all()}

    assert resumed.status == "completed"
    assert calls == ["first_tool", "second_tool", "second_tool"]
    assert status_by_node_attempt[("input", 1)] == "completed"
    assert status_by_node_attempt[("first", 1)] == "completed"
    assert status_by_node_attempt[("second", 1)] == "cancelled"
    assert status_by_node_attempt[("second", 2)] == "completed"
    assert status_by_node_attempt[("out", 1)] == "completed"
    assert resumed.merged_output_json["final"] == {"result": {"value": "second_tool"}}
    assert {"flow.node_recovery_retry", "flow.interrupted_resume_started", "flow.interrupted_resume_completed"} <= audit_actions


@pytest.mark.asyncio
async def test_recover_stale_v2_flow_runs_recovers_only_expired_runs(db, monkeypatch):
    class SimulatedCrash(BaseException):
        pass

    calls: list[str] = []
    crashed = False

    async def fake_execute_tool(tool_name, params, context):
        nonlocal crashed
        calls.append(tool_name)
        if tool_name == "second_tool" and not crashed:
            crashed = True
            raise SimulatedCrash("worker stopped")
        return {"value": tool_name}

    monkeypatch.setattr("app.services.flow_orchestration.dag.tool_node.execute_tool_with_plugins", fake_execute_tool)
    version = _make_v2_flow_version(
        db,
        "v2-stale-recovery",
        "f-v2-stale-recovery",
        "v2-stale-recovery",
        [
            {"id": "input", "type": "trigger"},
            {"id": "first", "type": "tool_step", "config": {"tool": "first_tool", "arguments": {}}},
            {"id": "second", "type": "tool_step", "config": {"tool": "second_tool", "arguments": {}}},
            {"id": "out", "type": "output"},
        ],
        [
            {"source_node_id": "input", "target_node_id": "first"},
            {"source_node_id": "first", "target_node_id": "second"},
            {"source_node_id": "second", "target_node_id": "out", "source_field": "result.value", "target_field": "value"},
        ],
    )

    with pytest.raises(SimulatedCrash):
        await execute_flow_version(db, flow_version_id=version.id, user_id="tester", initial_input={})

    run_id = (
        (await db.execute(select(FlowNodeRun).where(FlowNodeRun.node_id == "second")))
        .scalars()
        .one()
        .orchestrator_run_id
    )
    run = await db.get(OrchestratorAgentRun, run_id)
    policy = dict(run.routing_policy_json or {})
    runtime = dict(policy.get("runtime") or {})
    lease = dict(runtime.get("lease") or {})
    lease["lease_expires_at"] = (utc_now() - timedelta(seconds=1)).isoformat()
    runtime["lease"] = lease
    policy["runtime"] = runtime
    run.routing_policy_json = policy
    await db.flush()

    result = await recover_stale_v2_flow_runs(db, user_id="tester", reason="test stale recovery")
    runs_after = (await db.execute(select(FlowNodeRun).order_by(FlowNodeRun.created_at.asc()))).scalars().all()

    assert result["recovered_count"] == 1
    assert result["failed_count"] == 0
    assert calls == ["first_tool", "second_tool", "second_tool"]
    assert [(item.node_id, item.status, item.attempt) for item in runs_after] == [
        ("input", "completed", 1),
        ("first", "completed", 1),
        ("second", "cancelled", 1),
        ("second", "completed", 2),
        ("out", "completed", 1),
    ]
