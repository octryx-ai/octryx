"""Dispatch worker selection by explicit domain fields and configured routing rules, with its decisions."""

import uuid

import pytest
from sqlalchemy import select

from app.models import Project, TaskRoutingRule
from app.services.worker_pool.dispatch import select_dispatch_worker, select_dispatch_worker_with_decision
from app.services.worker_pool.helpers import explicit_required_domain, infer_required_domain
from tests.services.workers.worker_pool_service_support import _queued_task, _ready_worker


@pytest.mark.asyncio
async def test_worker_dispatch_domain_resolution_uses_only_explicit_fields(db, auth_user):
    project = (await db.execute(select(Project).where(Project.name == "acme-orders"))).scalar_one()
    task, queue_entry = await _queued_task(db, project=project, owner=auth_user, config={})

    assert explicit_required_domain(task, queue_entry) is None
    assert infer_required_domain(task, queue_entry) == "any"

    task.config = {"required_domain": "kubernetes"}
    await db.commit()

    assert explicit_required_domain(task, queue_entry) == "kubernetes"
    assert infer_required_domain(task, queue_entry) == "kubernetes"


@pytest.mark.asyncio
async def test_select_dispatch_worker_reports_no_available_workers(db, auth_user):
    project = (await db.execute(select(Project).where(Project.name == "acme-orders"))).scalar_one()
    task, queue_entry = await _queued_task(
        db,
        project=project,
        owner=auth_user,
        config={"required_domain": "kubernetes"},
        required_domain="kubernetes",
    )

    worker, decision = await select_dispatch_worker_with_decision(db, task=task, queue_entry=queue_entry)

    assert worker is None
    assert decision.status == "skipped"
    assert decision.reason == "no_available_workers"
    assert decision.required_domain == "kubernetes"


@pytest.mark.asyncio
async def test_select_dispatch_worker_reports_required_worker_unavailable(db, auth_user):
    project = (await db.execute(select(Project).where(Project.name == "acme-orders"))).scalar_one()
    worker = _ready_worker(project)
    db.add(worker)
    task, queue_entry = await _queued_task(
        db,
        project=project,
        owner=auth_user,
        config={"required_domain": "kubernetes"},
        required_domain="kubernetes",
    )
    queue_entry.required_worker_id = "missing-worker"
    await db.commit()

    selected, reason = await select_dispatch_worker(db, task=task, queue_entry=queue_entry)

    assert selected is None
    assert reason == "required_worker_unavailable"


@pytest.mark.asyncio
async def test_select_dispatch_worker_matches_configured_routing_rule_with_decision(db, auth_user):
    project = (await db.execute(select(Project).where(Project.name == "acme-orders"))).scalar_one()
    worker = _ready_worker(project, name="Rule Alex")
    db.add(worker)
    task, queue_entry = await _queued_task(
        db,
        project=project,
        owner=auth_user,
        config={"required_domain": "kubernetes"},
        required_domain="kubernetes",
        priority=9,
    )
    rule = TaskRoutingRule(
        id=str(uuid.uuid4()),
        project_id=project.id,
        priority=1,
        condition_type="domain_match",
        condition_config={"domain": "kubernetes"},
        target_type="specific_worker",
        target_config={"worker_id": worker.id},
        is_active=1,
    )
    db.add(rule)
    await db.commit()

    selected, decision = await select_dispatch_worker_with_decision(db, task=task, queue_entry=queue_entry)

    assert selected is not None
    assert selected.id == worker.id
    assert decision.status == "selected"
    assert decision.reason == "routing_rule_match"
    assert decision.matched_rule_id == rule.id


@pytest.mark.asyncio
async def test_select_dispatch_worker_requires_configured_route_without_explicit_domain(db, auth_user):
    project = (await db.execute(select(Project).where(Project.name == "acme-orders"))).scalar_one()
    worker = _ready_worker(project, name="No Policy Alex")
    db.add(worker)
    task, queue_entry = await _queued_task(db, project=project, owner=auth_user, config={}, priority=8)

    selected, reason = await select_dispatch_worker(db, task=task, queue_entry=queue_entry)

    assert selected is None
    assert reason == "routing_policy_missing"
