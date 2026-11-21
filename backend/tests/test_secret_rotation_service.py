from datetime import timedelta

import pytest
from sqlalchemy import select

from app.models import Notification, SecretRotationLog, User
from app.services.secret import (
    get_secret_value,
    process_secret_expiry_alerts,
    revoke_secret_value,
    rotate_secret_value,
    set_secret_value,
)
from app.time_utils import utc_now


@pytest.mark.asyncio
async def test_process_secret_expiry_alerts_creates_single_alert_per_expiry(db):
    await set_secret_value(
        db,
        tool_name="jira",
        field_name="api_token",
        project_id=None,
        value="top-secret",
        expires_at=utc_now() + timedelta(days=10),
    )
    await db.commit()

    first = await process_secret_expiry_alerts(db, alert_before_days=30)
    second = await process_secret_expiry_alerts(db, alert_before_days=30)

    assert first["alerts_created"] == 1
    assert second["alerts_created"] == 0

    notifications = (
        (await db.execute(select(Notification).where(Notification.type == "secret.expiring"))).scalars().all()
    )
    assert len(notifications) >= 1

    logs = (
        (await db.execute(select(SecretRotationLog).where(SecretRotationLog.action == "expiry_alert"))).scalars().all()
    )
    assert len(logs) == 1


@pytest.mark.asyncio
async def test_rotate_secret_value_updates_metadata_and_writes_rotation_log(db):
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    entry = await set_secret_value(
        db,
        tool_name="bitbucket",
        field_name="token",
        project_id=None,
        value="old-value",
        expires_at=utc_now() + timedelta(days=5),
    )
    await db.commit()

    payload = await rotate_secret_value(
        db,
        secret_id=entry.id,
        rotated_by=admin.id,
        value="new-value",
        expires_at=utc_now() + timedelta(days=45),
        note="routine rotation",
    )

    assert payload["id"] == entry.id
    assert payload["last_rotated_at"] is not None
    assert payload["days_until_expiry"] >= 44

    logs = (
        (
            await db.execute(
                select(SecretRotationLog).where(
                    SecretRotationLog.secret_id == entry.id,
                    SecretRotationLog.action == "rotated",
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(logs) == 1
    assert logs[0].rotated_by == admin.id
    assert logs[0].note == "routine rotation"


@pytest.mark.asyncio
async def test_expired_secret_value_fails_closed(db):
    entry = await set_secret_value(
        db,
        tool_name="github",
        field_name="github_token",
        project_id=None,
        value="expired-value",
        expires_at=utc_now() - timedelta(minutes=1),
    )
    await db.commit()

    assert await get_secret_value(db, secret_id=entry.id) is None
    assert await get_secret_value(db, tool_name="github", field_name="github_token", project_id=None) is None


@pytest.mark.asyncio
async def test_revoke_secret_value_expires_secret_and_writes_actor_log(db):
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    entry = await set_secret_value(
        db,
        tool_name="gitlab",
        field_name="gitlab_token",
        project_id=None,
        value="active-value",
        expires_at=utc_now() + timedelta(days=30),
    )
    await db.commit()

    payload = await revoke_secret_value(db, secret_id=entry.id, revoked_by=admin.id, note="compromised")

    assert payload["is_expired"] is True
    assert await get_secret_value(db, secret_id=entry.id) is None

    log = (
        await db.execute(
            select(SecretRotationLog).where(
                SecretRotationLog.secret_id == entry.id,
                SecretRotationLog.action == "revoked",
            )
        )
    ).scalar_one()
    assert log.rotated_by == admin.id
    assert log.note == "compromised"
