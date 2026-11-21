import uuid
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models import BackgroundWorkerRunState, Session, User
from app.services.notification_delivery.worker import NotificationDeliveryWorker
from app.services.outbound_webhook.worker import OutboundWebhookWorker
from app.services.prefetch import PrefetchJob, PrefetchRequest, PrefetchWorker
from app.services.secret.service import SecretExpiryWorker


@pytest.mark.asyncio
async def test_secret_expiry_worker_persists_success_run_state(db):
    session_factory = async_sessionmaker(db.bind, class_=AsyncSession, expire_on_commit=False)
    worker = SecretExpiryWorker(session_factory, interval_seconds=60, alert_before_days=30)

    result = await worker.run_once()

    assert result["status"] == "ok"
    row = await db.get(BackgroundWorkerRunState, "secret_expiry_worker")
    assert row is not None
    assert row.owner == "secrets"
    assert row.status == "success"
    assert row.error is None
    assert row.retryable is False
    assert row.run_count == 1
    assert row.failure_count == 0
    assert row.details_json["result_type"] == "dict"
    assert "expiring_secret_count" in row.details_json["counts"]


@pytest.mark.asyncio
async def test_delivery_workers_persist_empty_success_run_state(db):
    session_factory = async_sessionmaker(db.bind, class_=AsyncSession, expire_on_commit=False)

    notification_worker = NotificationDeliveryWorker(session_factory)
    outbound_worker = OutboundWebhookWorker(session_factory)

    assert await notification_worker.run_once() == 0
    assert await outbound_worker.run_once() == 0

    notification_state = await db.get(BackgroundWorkerRunState, "notification_delivery_worker")
    outbound_state = await db.get(BackgroundWorkerRunState, "outbound_webhook_worker")
    assert notification_state is not None
    assert notification_state.owner == "notifications"
    assert notification_state.status == "success"
    assert notification_state.processed_count == 0
    assert outbound_state is not None
    assert outbound_state.owner == "webhooks"
    assert outbound_state.status == "success"
    assert outbound_state.processed_count == 0


@pytest.mark.asyncio
async def test_prefetch_worker_persists_secret_safe_failure_run_state(db):
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    session = Session(id=str(uuid.uuid4()), user_id=admin.id, metadata_={})
    db.add(session)
    await db.commit()

    async def failing_execute_tool(tool_name, tool_args, tool_context):
        raise RuntimeError("Authorization token=super-secret ghp_thisShouldNotLeak failed")

    session_factory = async_sessionmaker(db.bind, class_=AsyncSession, expire_on_commit=False)
    worker = PrefetchWorker(session_factory, execute_tool_fn=failing_execute_tool)
    await worker.enqueue(
        PrefetchJob(
            session_id=session.id,
            user_id=admin.id,
            project_ids=[],
            roles=["admin"],
            project_config={},
            workspace_root=str(Path.cwd()),
            request_id="req-prefetch-failure",
            requests=[
                PrefetchRequest(
                    rule_id="acceptance",
                    tool_name="search_jira_tickets",
                    params={"query": "RIVER-1"},
                    prefetch_strategy="sequential",
                )
            ],
        )
    )

    with pytest.raises(RuntimeError):
        await worker.run_once()

    row = await db.get(BackgroundWorkerRunState, "prefetch_worker")
    assert row is not None
    assert row.owner == "prefetch"
    assert row.status == "failed"
    assert row.retryable is True
    assert row.run_count == 1
    assert row.failure_count == 1
    assert row.details_json == {"result_type": "error"}
    assert row.error == "Authorization token=[REDACTED] [REDACTED] failed"
    assert "super-secret" not in row.error
    assert "ghp_thisShouldNotLeak" not in row.error
