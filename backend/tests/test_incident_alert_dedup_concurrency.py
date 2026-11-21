"""Identical deliveries at the same time start exactly one run (the webhook row lock + the dedup).

Runs the product's ``receive_alert`` on a database built by ``alembic upgrade head`` alone, each delivery in its
own session and with its own delivery id. On PostgreSQL (``OCTRYX_TEST_POSTGRES_URL``, a disposable
server; the scratch database is created and dropped here) the deliveries really run at the same time and the
``SELECT ... FOR UPDATE`` on the webhook row serialises decide-and-record. SQLite has no row lock, so there the
same deliveries run one after the other and prove the decision itself.
"""

from __future__ import annotations

import asyncio
import uuid
from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models import Project, Task, TaskRun, User
from app.models.integration.webhook import Webhook, WebhookEvent
from app.services.inbound_alerts import trigger
from tests.alembic_model_parity_support import DIALECTS, migrated_database
from tests.s5_alert_dedup_support import A, B, QueueOnly, am  # noqa: F401


async def _seed(maker) -> tuple[str, str, str]:
    async with maker() as db:
        owner = User(id=str(uuid.uuid4()), username=f"s5-owner-{uuid.uuid4().hex[:8]}",
                     email=f"s5-{uuid.uuid4().hex[:8]}@example.com", password_hash="x", is_active=True)
        project = Project(id=str(uuid.uuid4()), name=f"s5-alerts-{uuid.uuid4().hex[:8]}", config={})
        db.add_all([owner, project])
        await db.flush()
        task = Task(dispatch_binding="task_definition", id=str(uuid.uuid4()), project_id=project.id, name="Incident analysis", description="",
                    task_type="agent_run", agent_type="diagnosis", owner_id=owner.id, is_active=True,
                    config={"prompt": "Analyse the alert.", "capability_class": "read_only"})
        db.add(task)
        await db.flush()
        webhook = Webhook(id=str(uuid.uuid4()), project_id=project.id, owner_id=owner.id, name="Alertmanager",
                          source_type="alertmanager", task_id=task.id, is_active=True, alert_filter="critical_warning",
                          group_window_minutes=30, rate_limit_per_hour=20, accept_untimestamped=False)
        db.add(webhook)
        await db.commit()
        return owner.id, task.id, webhook.id


async def _deliveries(url: str, payloads: list[dict], *, concurrent: bool, monkeypatch) -> tuple[list[str], int]:
    engine = create_async_engine(url)
    try:
        maker = async_sessionmaker(engine, expire_on_commit=False)
        owner_id, task_id, webhook_id = await _seed(maker)

        async def principal(db, _webhook):  # the service user's roles are not under test here
            return await db.get(User, owner_id)

        monkeypatch.setattr(trigger, "ensure_webhook_service_user", principal)

        async def one(payload: dict) -> str:
            async with maker() as db:
                webhook = await db.get(Webhook, webhook_id)
                result = await trigger.receive_alert(db, webhook=webhook, body=b"{}", payload=payload,
                                                     verified=True, delivery_key=f"id:{uuid.uuid4().hex}",
                                                     scheduler=QueueOnly(db))
                return result["outcome"]

        if concurrent:
            outcomes = list(await asyncio.gather(*(one(payload) for payload in payloads)))
        else:
            outcomes = [await one(payload) for payload in payloads]
        async with maker() as db:
            runs = int((await db.execute(select(func.count()).select_from(TaskRun)
                                         .where(TaskRun.task_id == task_id))).scalar_one())
            events = int((await db.execute(select(func.count()).select_from(WebhookEvent)
                                           .where(WebhookEvent.webhook_id == webhook_id))).scalar_one())
        assert events == len(payloads), "every delivery is recorded"
        return sorted(outcomes), runs
    finally:
        await engine.dispose()


@pytest.mark.parametrize("dialect", DIALECTS)
def test_identical_deliveries_at_the_same_time_start_exactly_one_run(dialect, tmp_path: Path, monkeypatch):
    with migrated_database(dialect, tmp_path) as database:
        concurrent = dialect == "postgresql"
        two = asyncio.run(_deliveries(database.url, [am(A), am(A)], concurrent=concurrent, monkeypatch=monkeypatch))
        assert two == (["grouped", "started"], 1)
        # A burst: the same group, one that gained an alert, and a refire of the same alert.
        burst = asyncio.run(_deliveries(database.url, [am(A), am(A), am(A, B), am(("fp-a", "2026-10-15T11:00:00Z"))],
                                        concurrent=concurrent, monkeypatch=monkeypatch))
        assert burst == (["grouped", "grouped", "grouped", "started"], 1)
