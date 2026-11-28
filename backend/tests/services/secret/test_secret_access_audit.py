from __future__ import annotations

import time
import uuid
from types import SimpleNamespace

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import AsyncAdaptedQueuePool

from app.db.core import independent_write_engine
from app.models import OutboundWebhookDelivery, SecretAccessAuditLog, User
from app.services.data_access import as_viewer
from app.services.outbound_webhook import (
    create_outbound_webhook,
    emit_outbound_webhook_event,
    process_outbound_webhook_delivery_batch,
)
from app.services.secret import SecretAccessAuditError, get_secret_value
from app.services.secret import access as secret_access
from app.services.secret.release import release_unreferenced_secrets
from tests.conftest import _test_engine, _test_session_factory
from tests.devices.device_support import user_named
from tests.support.secret_access_audit_support import (
    VALUE,
    assert_holds_no_value,
    assert_read_once,
    owner_and_workspace,
    reads_of,
    stored,
)


async def test_a_read_records_the_person_the_secret_the_purpose_and_the_secrets_workspace(db):
    owner, workspace = await owner_and_workspace(db)
    secret = await stored(db, tool_name="demo-tool", field_name="token", project_id=workspace.id)
    with as_viewer(owner.id):
        assert await get_secret_value(db, secret_id=secret.id, purpose="test.read") == VALUE
    await assert_read_once(db, secret_id=secret.id, purpose="test.read", workspace_id=workspace.id, user=owner)


async def test_a_platform_job_read_records_the_maintenance_site_and_its_reason(db):
    secret = await stored(db, tool_name="demo-tool", field_name="token", project_id=None)
    assert await get_secret_value(db, secret_id=secret.id, purpose="test.job") == VALUE
    row = await assert_read_once(db, secret_id=secret.id, purpose="test.job", workspace_id=None)
    assert row.principal.startswith("platform:") and row.actor_user_id is None
    assert row.context_json["reason"] == "test harness"


async def test_a_read_whose_audit_row_cannot_be_written_is_refused(db, monkeypatch):
    secret = await stored(db, tool_name="demo-tool", field_name="token", project_id=None)
    monkeypatch.setattr(secret_access, "READ_ACTION", None)
    with pytest.raises(SecretAccessAuditError, match="audit row was not written"):
        await get_secret_value(db, secret_id=secret.id, purpose="test.read")
    assert await reads_of(db, secret_id=secret.id) == []


async def test_a_background_delivery_whose_audit_row_fails_is_retried_visibly_and_never_sent(db, monkeypatch):
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    await create_outbound_webhook(db, current_user=admin, payload={
        "name": "audit-failure", "url": "https://hooks.example.com/in", "event_types": ["task.completed"]})
    await emit_outbound_webhook_event(db, event_type="task.completed", payload={"task_id": "OCX-101"})
    await db.commit()
    posted: list[str] = []

    class Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_exc):
            return False

        async def post(self, url, **_kwargs):
            posted.append(url)
            return httpx.Response(200, request=httpx.Request("POST", url))

    monkeypatch.setattr("app.services.outbound_webhook.httpx.AsyncClient", lambda *args, **kwargs: Client())
    monkeypatch.setattr(secret_access, "READ_ACTION", None)
    await process_outbound_webhook_delivery_batch(db)
    delivery = (await db.execute(select(OutboundWebhookDelivery))).scalar_one()
    assert posted == [] and delivery.status == "retrying"
    assert "error_type=SecretAccessAuditError" in delivery.error


async def test_a_released_secret_keeps_its_reads_in_its_workspace_hidden_from_others(db):
    owner, workspace = await owner_and_workspace(db)
    other = await user_named(db, f"audit-other-{uuid.uuid4().hex[:8]}")
    secret = await stored(db, tool_name="demo-tool", field_name="token", project_id=workspace.id)
    with as_viewer(owner.id):
        await get_secret_value(db, secret_id=secret.id, purpose="test.read")
    [row_id] = [row.id for row in await reads_of(db, secret_id=secret.id)]
    await release_unreferenced_secrets(db, [secret.id])
    db.expunge_all()
    with as_viewer(owner.id):
        row = await db.get(SecretAccessAuditLog, row_id)
        assert (row.secret_id, row.project_id) == (None, workspace.id)
    db.expunge_all()
    with as_viewer(other.id):
        assert (await db.execute(select(SecretAccessAuditLog).where(SecretAccessAuditLog.id == row_id))).first() is None


@pytest.fixture
def own_sessions():
    secret_access.RECENT_USES.clear()
    yield
    secret_access.RECENT_USES.clear()


async def _committed_secret() -> str:
    async with _test_session_factory() as session:
        secret = await stored(session, tool_name="demo-tool", field_name=f"token-{uuid.uuid4().hex[:8]}",
                              project_id=None)
        await session.commit()
        return secret.id


async def _committed_reads(secret_id: str) -> list[SecretAccessAuditLog]:
    async with _test_session_factory() as session:
        return await reads_of(session, secret_id=secret_id)


@pytest.mark.committed_db
async def test_a_read_in_a_clean_transaction_is_recorded_beyond_the_callers_rollback(db, own_sessions):
    secret_id = await _committed_secret()
    async with _test_session_factory() as session:
        assert await get_secret_value(session, secret_id=secret_id, purpose="test.read") == VALUE
        await session.rollback()
    [row] = await _committed_reads(secret_id)
    assert_holds_no_value(row)


@pytest.mark.committed_db
async def test_a_read_after_the_caller_wrote_shares_the_callers_transaction(db, own_sessions):
    secret_id = await _committed_secret()
    async with _test_session_factory() as session:
        await user_named(session, f"audit-writer-{uuid.uuid4().hex[:8]}")
        for _ in range(2):
            assert await get_secret_value(session, secret_id=secret_id, purpose="test.read") == VALUE
        assert len(await reads_of(session, secret_id=secret_id)) == 1
        await session.rollback()
        assert await _committed_reads(secret_id) == []
        await user_named(session, f"audit-writer-{uuid.uuid4().hex[:8]}")
        await get_secret_value(session, secret_id=secret_id, purpose="test.read")
        await session.commit()
        await get_secret_value(session, secret_id=secret_id, purpose="test.read")
    assert len(await _committed_reads(secret_id)) == 1


@pytest.mark.committed_db
async def test_repeated_reads_record_one_row_per_principal_secret_and_purpose_per_window(db, own_sessions,
                                                                                         monkeypatch):
    secret_id = await _committed_secret()
    async with _test_session_factory() as session:
        for purpose in ("test.read", "test.read", "test.other"):
            await get_secret_value(session, secret_id=secret_id, purpose=purpose)
            await session.rollback()
        later = time.monotonic() + secret_access.AUDIT_WINDOW.total_seconds() + 1
        monkeypatch.setattr(secret_access, "time", SimpleNamespace(monotonic=lambda: later))
        await get_secret_value(session, secret_id=secret_id, purpose="test.read")
    assert sorted(row.purpose for row in await _committed_reads(secret_id)) == ["test.other", "test.read", "test.read"]


@pytest.mark.committed_db
async def test_a_first_read_is_recorded_while_the_caller_holds_every_slot_of_its_pool(db, own_sessions):
    secret_id = await _committed_secret()
    caller = create_async_engine(_test_engine.url, connect_args={"check_same_thread": False, "timeout": 120},
                                 poolclass=AsyncAdaptedQueuePool, pool_size=1, max_overflow=0, pool_timeout=0.5)
    try:
        async with AsyncSession(caller) as session:
            assert await get_secret_value(session, secret_id=secret_id, purpose="test.read") == VALUE
    finally:
        await independent_write_engine(caller).dispose()
        await caller.dispose()
    assert len(await _committed_reads(secret_id)) == 1


@pytest.mark.committed_db
async def test_a_read_in_a_released_savepoint_counts_only_once_the_outer_transaction_commits(db, own_sessions):
    secret_id = await _committed_secret()
    async with _test_session_factory() as session:
        await user_named(session, f"audit-writer-{uuid.uuid4().hex[:8]}")
        async with session.begin_nested():
            await get_secret_value(session, secret_id=secret_id, purpose="test.read")
        await get_secret_value(session, secret_id=secret_id, purpose="test.read")
        assert len(await reads_of(session, secret_id=secret_id)) == 1
        await session.rollback()
        await get_secret_value(session, secret_id=secret_id, purpose="test.read")
    assert len(await _committed_reads(secret_id)) == 1


@pytest.mark.committed_db
async def test_a_read_in_a_rolled_back_savepoint_is_recorded_again_in_the_enclosing_transaction(db, own_sessions):
    secret_id = await _committed_secret()
    async with _test_session_factory() as session:
        await user_named(session, f"audit-writer-{uuid.uuid4().hex[:8]}")
        savepoint = await session.begin_nested()
        await get_secret_value(session, secret_id=secret_id, purpose="test.read")
        await savepoint.rollback()
        await get_secret_value(session, secret_id=secret_id, purpose="test.read")
        await session.commit()
        await get_secret_value(session, secret_id=secret_id, purpose="test.read")
    assert len(await _committed_reads(secret_id)) == 1
