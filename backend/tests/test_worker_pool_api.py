"""Worker pool API configuration and routing rules, distributed worker registration, autoscaling and manifests."""

import uuid
from datetime import timedelta

import pytest
from sqlalchemy import select

import app.main as main_module
from app.models import (
    AgentWorker,
    Project,
    Task,
    TaskQueueEntry,
    TaskRun,
    User,
    WorkerDomainExpertise,
    WorkerOnboarding,
    WorkerRuntimeState,
)
from app.services.worker_pool.runtime import DistributedWorker
from app.services.worker_pool.state import get_or_create_worker_pool_config
from app.services.worker_pool_service import build_project_worker_manifests, evaluate_pool_scaling
from app.time_utils import utc_now


@pytest.mark.asyncio
async def test_worker_pool_api_config_and_routing_rules(client, auth_headers, db):
    project = (await db.execute(select(Project).where(Project.name == "acme-orders"))).scalar_one()

    pool_resp = await client.get(f"/api/v1/workers/projects/{project.id}/pool-config", headers=auth_headers)
    assert pool_resp.status_code == 200, pool_resp.text
    assert pool_resp.json()["queue_backend"] == "database"

    updated_pool = await client.put(
        f"/api/v1/workers/projects/{project.id}/pool-config",
        json={
            "min_workers": 2,
            "max_workers": 6,
            "current_workers": 3,
            "queue_backend": "redis",
            "hpa_target_queue_depth": 7,
        },
        headers=auth_headers,
    )
    assert updated_pool.status_code == 200, updated_pool.text
    assert updated_pool.json()["current_workers"] == 3
    assert updated_pool.json()["queue_backend"] == "redis"

    rate_resp = await client.put(
        f"/api/v1/workers/projects/{project.id}/rate-limits",
        json={
            "max_requests_per_minute": 25,
            "max_tokens_per_hour": 120000,
            "max_cost_per_hour": 4.5,
            "on_cost_limit": "pause_low_priority",
        },
        headers=auth_headers,
    )
    assert rate_resp.status_code == 200, rate_resp.text
    assert rate_resp.json()["max_requests_per_minute"] == 25
    assert rate_resp.json()["on_cost_limit"] == "pause_low_priority"

    rule_resp = await client.post(
        f"/api/v1/workers/projects/{project.id}/routing-rules",
        json={
            "priority": 10,
            "condition_type": "domain_match",
            "condition_config": {"domain": "kubernetes"},
            "target_type": "specific_worker",
            "target_config": {"worker_id": "worker-123"},
        },
        headers=auth_headers,
    )
    assert rule_resp.status_code == 200, rule_resp.text
    assert rule_resp.json()["condition_type"] == "domain_match"

    rules_resp = await client.get(f"/api/v1/workers/projects/{project.id}/routing-rules", headers=auth_headers)
    assert rules_resp.status_code == 200, rules_resp.text
    assert len(rules_resp.json()) == 1


@pytest.mark.asyncio
async def test_worker_pool_api_rejects_a_text_matching_rule(client, auth_headers, db):
    project = (await db.execute(select(Project).where(Project.name == "acme-orders"))).scalar_one()

    response = await client.post(
        f"/api/v1/workers/projects/{project.id}/routing-rules",
        json={
            "priority": 10,
            "condition_type": "text_match",
            "condition_config": {"words": ["pod"]},
            "target_type": "worker_pool",
            "target_config": {},
        },
        headers=auth_headers,
    )

    assert response.status_code == 422
    assert "condition_type must be one of: domain_match, priority_level, always, worker_expertise" in response.text


@pytest.mark.asyncio
@pytest.mark.committed_db
async def test_distributed_worker_registration_and_queue_depth_metric(client, auth_headers, db):
    project = (await db.execute(select(Project).where(Project.name == "acme-orders"))).scalar_one()
    worker = AgentWorker(
        id=str(uuid.uuid4()),
        project_id=project.id,
        name="Distributed Alex",
        role="Ops",
        is_active=True,
    )
    worker.onboarding = WorkerOnboarding(
        worker_id=worker.id, onboarding_status="ready", ready_at=utc_now(), warmup_period_hours=0
    )
    worker.runtime_state = WorkerRuntimeState(
        worker_id=worker.id,
        status="active",
        current_priority="idle",
        active_tasks_count=0,
        max_parallel_tasks=1,
        available_slots=1,
    )
    db.add(worker)
    await db.commit()

    worker_process = DistributedWorker(main_module.app.state.async_session_factory, worker.id, backend="database")
    try:
        payload = await worker_process.start()
        await db.commit()

        assert payload["status"] == "ready"
        assert payload["backend"] == "database"

        metrics = await client.get("/metrics", headers=auth_headers)
        assert metrics.status_code == 200
        # The database queue has no depth series: its task runs are counted when queued, started and finished.
        assert "# TYPE octryx_task_runs_enqueued_total counter" in metrics.text
    finally:
        await worker_process.stop()


def _seed_kubernetes_expert_worker(db, project):
    worker = AgentWorker(
        id=str(uuid.uuid4()),
        project_id=project.id,
        name="Scale Alex",
        role="SRE",
        is_active=True,
    )
    worker.onboarding = WorkerOnboarding(
        worker_id=worker.id, onboarding_status="ready", ready_at=utc_now(), warmup_period_hours=0
    )
    worker.runtime_state = WorkerRuntimeState(
        worker_id=worker.id,
        status="active",
        current_priority="idle",
        active_tasks_count=0,
        max_parallel_tasks=3,
        available_slots=3,
    )
    db.add_all(
        [
            worker,
            WorkerDomainExpertise(
                id=str(uuid.uuid4()),
                worker_id=worker.id,
                domain="kubernetes",
                expertise_level="expert",
                tasks_completed=10,
                success_rate=0.9,
            ),
        ]
    )
    return worker


async def _seed_pending_kubernetes_incident(db, project, admin):
    task = Task(dispatch_binding="task_definition",
        id=str(uuid.uuid4()),
        project_id=project.id,
        name="Critical pod incident",
        description="OOM in kubernetes",
        task_type="agent_run",
        agent_type="diagnosis",
        owner_id=admin.id,
        is_active=True,
        config={"queue_priority": 10, "required_domain": "kubernetes"},
    )
    db.add(task)
    await db.flush()
    task_run = TaskRun(
        id=str(uuid.uuid4()),
        task_id=task.id,
        session_id=None,
        status="queued",
        started_by=admin.id,
        input_={},
    )
    db.add(task_run)
    await db.flush()
    queue_entry = TaskQueueEntry(
        id=str(uuid.uuid4()),
        task_run_id=task_run.id,
        project_id=project.id,
        task_type="incident",
        priority=10,
        status="pending",
        required_domain="kubernetes",
    )
    db.add(queue_entry)
    await db.commit()
    return queue_entry


async def _assert_scaled_up_manifests(client, auth_headers, project_id):
    manifests_resp = await client.get(f"/api/v1/workers/projects/{project_id}/manifests", headers=auth_headers)
    assert manifests_resp.status_code == 200, manifests_resp.text
    manifests = manifests_resp.json()
    assert manifests["pool_config"]["current_workers"] >= 2
    assert len(manifests["manifests"]) >= 1
    deployment = manifests["manifests"][0]["deployment"]
    hpa = manifests["manifests"][0]["hpa"]
    env_names = {entry["name"] for entry in deployment["spec"]["template"]["spec"]["containers"][0]["env"]}
    assert {"WORKER_ID", "WORKER_ROLE", "WORKER_DOMAINS", "WORKER_MAX_PARALLEL"} <= env_names
    assert hpa["spec"]["metrics"][0]["external"]["metric"]["name"] == "octryx_queue_depth"


@pytest.mark.asyncio
async def test_worker_pool_autoscale_and_manifest_api(client, auth_headers, db):
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    project = (await db.execute(select(Project).where(Project.name == "acme-orders"))).scalar_one()
    _seed_kubernetes_expert_worker(db, project)
    queue_entry = await _seed_pending_kubernetes_incident(db, project, admin)

    cfg_resp = await client.put(
        f"/api/v1/workers/projects/{project.id}/pool-config",
        json={
            "min_workers": 1,
            "max_workers": 4,
            "current_workers": 1,
            "scale_up_threshold": 1,
            "scale_down_threshold": 1,
            "scale_up_cooldown_minutes": 1,
            "scale_down_cooldown_minutes": 1,
            "hpa_target_queue_depth": 3,
        },
        headers=auth_headers,
    )
    assert cfg_resp.status_code == 200, cfg_resp.text

    up_resp = await client.post(f"/api/v1/workers/projects/{project.id}/autoscale/run", headers=auth_headers)
    assert up_resp.status_code == 200, up_resp.text
    up_summary = up_resp.json()
    assert up_summary["action"] == "up"
    assert up_summary["current_workers"] >= 2
    await _assert_scaled_up_manifests(client, auth_headers, project.id)

    queue_entry.status = "completed"
    queue_entry.completed_at = utc_now()
    pool_row = await get_or_create_worker_pool_config(db, project.id)
    pool_row.last_scale_at = utc_now() - timedelta(minutes=5)
    await db.commit()

    summary = await evaluate_pool_scaling(db, project_id=project.id)
    assert summary["action"] == "down"
    assert summary["current_workers"] == 1
    pool = await build_project_worker_manifests(db, project_id=project.id, current_user=admin)
    assert pool["pool_config"]["current_workers"] == 1

    metrics = await client.get("/metrics", headers=auth_headers)
    assert metrics.status_code == 200
    assert "# TYPE octryx_task_runs_enqueued_total counter" in metrics.text

    health = await client.get("/api/v1/health", headers=auth_headers)
    assert health.status_code == 200
    assert "worker_pool_worker" in health.text
