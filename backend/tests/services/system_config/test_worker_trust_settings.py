from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.models import AgentWorker, Project
from app.services.system_config import (
    AGENT_WORKER_TRUST_DELTA_SUCCESS_KEY,
    get_worker_trust_deltas,
    set_system_config_value,
)
from app.services.worker import record_worker_trust_event
from app.services.worker.policy import DEFAULT_TRUST_DELTAS


async def _create_worker(db, *, trust_score: float = 0.5) -> AgentWorker:
    project = (await db.execute(select(Project).where(Project.name == "acme-orders"))).scalar_one()
    worker = AgentWorker(
        id=str(uuid.uuid4()),
        project_id=project.id,
        name="Trust Config Worker",
        role="Incident Responder",
        trust_score=trust_score,
        autonomy_level="semi_auto",
        is_active=True,
    )
    db.add(worker)
    await db.commit()
    return worker


@pytest.mark.asyncio
async def test_worker_trust_event_uses_default_delta_when_no_override_exists(db):
    worker = await _create_worker(db, trust_score=0.5)

    event = await record_worker_trust_event(db, worker=worker, event_type="success")

    assert event["trust_delta"] == DEFAULT_TRUST_DELTAS["success"]
    assert event["new_trust_score"] == 0.55


@pytest.mark.asyncio
async def test_worker_trust_event_uses_db_override_for_default_delta(db):
    worker = await _create_worker(db, trust_score=0.4)
    await set_system_config_value(db, key=AGENT_WORKER_TRUST_DELTA_SUCCESS_KEY, value="0.2")
    await db.commit()

    event = await record_worker_trust_event(db, worker=worker, event_type="success")

    assert event["trust_delta"] == 0.2
    assert event["new_trust_score"] == 0.6


@pytest.mark.asyncio
async def test_explicit_worker_trust_delta_overrides_db_backed_default(db):
    worker = await _create_worker(db, trust_score=0.4)
    await set_system_config_value(db, key=AGENT_WORKER_TRUST_DELTA_SUCCESS_KEY, value="0.2")
    await db.commit()

    event = await record_worker_trust_event(
        db,
        worker=worker,
        event_type="success",
        explicit_delta=0.05,
    )

    assert event["trust_delta"] == 0.05
    assert event["new_trust_score"] == 0.45


@pytest.mark.asyncio
async def test_worker_trust_delta_overrides_are_bounded(db):
    await set_system_config_value(db, key=AGENT_WORKER_TRUST_DELTA_SUCCESS_KEY, value="2.5")
    await db.commit()

    trust_deltas = await get_worker_trust_deltas(db)

    assert trust_deltas["success"] == 1.0
