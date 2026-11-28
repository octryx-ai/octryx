"""Encrypted secret storage for tool and provider credentials."""

import asyncio
import logging
import uuid
from datetime import datetime, timedelta
from typing import Any
from urllib.parse import urlencode

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import Role, SecretRotationLog, StoredSecret, User, UserRole
from ...time_utils import ensure_utc, utc_now, utc_now_aware
from ..background_worker_state import (
    record_background_worker_failure,
    record_background_worker_success,
)
from ..team_notification import create_notification
from .access import reveal_stored_secret
from .crypto import encrypt_secret

_SECRET_REF_PREFIX = "secret:"
_SECRET_REF_FIELD_SUFFIX = "_secret_ref"
_PROJECT_SCOPE_NOT_PROVIDED = object()
logger = logging.getLogger(__name__)


def secret_ref_label(secret_id: str | None) -> str | None:
    if not secret_id:
        return None
    return f"{_SECRET_REF_PREFIX}{secret_id}"


def normalize_secret_ref(value: Any) -> str | None:
    """Return the stored secret id from either raw ids or public ``secret:<id>`` labels."""
    if value in (None, ""):
        return None
    text = str(value).strip()
    if not text:
        return None
    if text.startswith(_SECRET_REF_PREFIX):
        text = text[len(_SECRET_REF_PREFIX) :].strip()
    return text or None


def is_secret_ref_field(field_name: str) -> bool:
    return str(field_name or "").endswith(_SECRET_REF_FIELD_SUFFIX)


def secret_ref_field_name(field_name: str) -> str:
    normalized = str(field_name or "").strip()
    if not normalized:
        raise ValueError("secret field name is required")
    if is_secret_ref_field(normalized):
        return normalized
    return f"{normalized}{_SECRET_REF_FIELD_SUFFIX}"


def secret_value_field_name(ref_field_name: str) -> str:
    normalized = str(ref_field_name or "").strip()
    if not is_secret_ref_field(normalized):
        raise ValueError("secret ref field name must end with _secret_ref")
    return normalized[: -len(_SECRET_REF_FIELD_SUFFIX)]


def secret_reference_contract() -> dict[str, Any]:
    """Return audit-safe metadata describing the secret-reference boundary."""
    return {
        "public_label_prefix": _SECRET_REF_PREFIX,
        "config_ref_suffix": _SECRET_REF_FIELD_SUFFIX,
        "persisted_value": "stored_secret_id",
        "public_label": "secret:<stored_secret_id>",
        "raw_secret_storage": "StoredSecret.encrypted_value",
        "resolution_owner": "backend/app/services/secret/service.py",
        "resolution_scope": "tool_name + field_name + project_id",
        "raw_secret_payloads": "accepted only at save/test boundary and converted before persistence",
    }


def _secret_entry_matches_expected_scope(
    entry: StoredSecret,
    *,
    expected_tool_name: str | None,
    expected_field_name: str | None,
    expected_project_id: str | None | object,
) -> bool:
    if expected_tool_name is not None and entry.tool_name != expected_tool_name:
        return False
    if expected_field_name is not None and entry.field_name != expected_field_name:
        return False
    if expected_project_id is not _PROJECT_SCOPE_NOT_PROVIDED and entry.project_id != expected_project_id:
        return False
    return True


def _parse_optional_datetime(value: Any) -> datetime | None:
    if value in (None, "", 0, "0"):
        return None
    if isinstance(value, datetime):
        return ensure_utc(value)
    text = str(value).strip()
    if not text:
        return None
    return ensure_utc(datetime.fromisoformat(text.replace("Z", "+00:00")))


def serialize_secret_entry(entry: StoredSecret) -> dict[str, Any]:
    expires_at = ensure_utc(entry.expires_at)
    now = utc_now_aware()
    days_until_expiry = None
    if expires_at is not None:
        days_until_expiry = int((expires_at - now).total_seconds() // 86400)
    return {
        "id": entry.id,
        "project_id": entry.project_id,
        "tool_name": entry.tool_name,
        "field_name": entry.field_name,
        "expires_at": expires_at.isoformat() if expires_at else None,
        "last_rotated_at": ensure_utc(entry.last_rotated_at).isoformat() if entry.last_rotated_at else None,
        "created_at": ensure_utc(entry.created_at).isoformat() if entry.created_at else None,
        "updated_at": ensure_utc(entry.updated_at).isoformat() if entry.updated_at else None,
        "days_until_expiry": days_until_expiry,
        "is_expired": bool(expires_at and expires_at <= now),
    }


def serialize_secret_rotation_log(entry: SecretRotationLog) -> dict[str, Any]:
    return {
        "id": entry.id,
        "secret_id": entry.secret_id,
        "action": entry.action,
        "rotated_by": entry.rotated_by,
        "previous_expires_at": ensure_utc(entry.previous_expires_at).isoformat() if entry.previous_expires_at else None,
        "new_expires_at": ensure_utc(entry.new_expires_at).isoformat() if entry.new_expires_at else None,
        "note": entry.note,
        "created_at": ensure_utc(entry.created_at).isoformat() if entry.created_at else None,
    }


async def get_secret_entry(
    db: AsyncSession,
    *,
    tool_name: str,
    field_name: str,
    project_id: str | None,
) -> StoredSecret | None:
    stmt = select(StoredSecret).where(
        StoredSecret.tool_name == tool_name,
        StoredSecret.field_name == field_name,
    )
    if project_id is None:
        stmt = stmt.where(StoredSecret.project_id.is_(None))
    else:
        stmt = stmt.where(StoredSecret.project_id == project_id)
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def set_secret_value(
    db: AsyncSession,
    *,
    tool_name: str,
    field_name: str,
    project_id: str | None,
    value: str,
    expires_at: datetime | str | None = None,
) -> StoredSecret:
    entry = await get_secret_entry(db, tool_name=tool_name, field_name=field_name, project_id=project_id)
    if not entry:
        entry = StoredSecret(
            tool_name=tool_name,
            field_name=field_name,
            project_id=project_id,
            encrypted_value="",
            name=f"{tool_name}_{field_name}",
            secret_type=tool_name,
        )
        db.add(entry)
    entry.encrypted_value = encrypt_secret(value)
    entry.last_rotated_at = utc_now()
    if expires_at is not None:
        entry.expires_at = _parse_optional_datetime(expires_at)
    await db.flush()
    return entry


async def get_secret_value(
    db: AsyncSession,
    *,
    secret_id: str | None = None,
    tool_name: str | None = None,
    field_name: str | None = None,
    project_id: str | None = None,
    expected_tool_name: str | None = None,
    expected_field_name: str | None = None,
    expected_project_id: str | None | object = _PROJECT_SCOPE_NOT_PROVIDED,
    purpose: str,
) -> str | None:
    entry = None
    if secret_id:
        normalized_secret_id = normalize_secret_ref(secret_id)
        if not normalized_secret_id:
            return None
        entry = await db.get(StoredSecret, normalized_secret_id)
    elif tool_name and field_name:
        entry = await get_secret_entry(db, tool_name=tool_name, field_name=field_name, project_id=project_id)
    if not entry:
        return None
    expires_at = ensure_utc(entry.expires_at)
    if expires_at is not None and expires_at <= utc_now_aware():
        logger.warning(
            "Refused expired secret resolution",
            extra={"secret_id": entry.id, "tool_name": entry.tool_name, "field_name": entry.field_name},
        )
        return None
    if not _secret_entry_matches_expected_scope(
        entry,
        expected_tool_name=expected_tool_name,
        expected_field_name=expected_field_name,
        expected_project_id=expected_project_id,
    ):
        logger.warning(
            "Refused secret ref resolution outside expected scope",
            extra={
                "secret_id": entry.id,
                "expected_tool_name": expected_tool_name,
                "expected_field_name": expected_field_name,
                "expected_project_id": None
                if expected_project_id is _PROJECT_SCOPE_NOT_PROVIDED
                else expected_project_id,
                "actual_tool_name": entry.tool_name,
                "actual_field_name": entry.field_name,
                "actual_project_id": entry.project_id,
            },
        )
        return None
    return await reveal_stored_secret(db, entry, purpose=purpose)


async def resolve_secret_refs(
    db: AsyncSession,
    config: dict,
    *,
    tool_name: str | None = None,
    project_id: str | None = None,
    purpose: str,
) -> dict:
    """Resolve explicit ``*_secret_ref`` fields without falling back across scopes."""
    resolved = dict(config)
    for key, value in list(config.items()):
        if is_secret_ref_field(key):
            field_name = secret_value_field_name(key)
            secret_id = normalize_secret_ref(value)
            if not secret_id:
                continue
            secret_value = await get_secret_value(
                db,
                secret_id=secret_id,
                expected_tool_name=tool_name,
                expected_field_name=field_name if tool_name else None,
                expected_project_id=project_id if tool_name else _PROJECT_SCOPE_NOT_PROVIDED,
                purpose=purpose,
            )
            if secret_value is not None:
                resolved[field_name] = secret_value
    return resolved


async def list_secret_entries(
    db: AsyncSession,
    *,
    expiring_within_days: int | None = None,
    limit: int = 200,
) -> list[dict[str, Any]]:
    stmt = select(StoredSecret).order_by(StoredSecret.updated_at.desc()).limit(max(1, min(int(limit or 200), 500)))
    if expiring_within_days is not None:
        now = utc_now()
        threshold = now + timedelta(days=max(0, int(expiring_within_days)))
        stmt = stmt.where(
            StoredSecret.expires_at.is_not(None),
            StoredSecret.expires_at <= threshold,
        )
    rows = (await db.execute(stmt)).scalars().all()
    return [serialize_secret_entry(row) for row in rows]


async def list_secret_rotation_logs(db: AsyncSession, *, limit: int = 100) -> list[dict[str, Any]]:
    rows = (
        (
            await db.execute(
                select(SecretRotationLog)
                .order_by(SecretRotationLog.created_at.desc())
                .limit(max(1, min(int(limit or 100), 500)))
            )
        )
        .scalars()
        .all()
    )
    return [serialize_secret_rotation_log(row) for row in rows]


async def update_secret_metadata(
    db: AsyncSession,
    *,
    secret_id: str,
    expires_at: datetime | str | None,
) -> dict[str, Any]:
    entry = await db.get(StoredSecret, secret_id)
    if entry is None:
        raise ValueError("Secret not found")
    entry.expires_at = _parse_optional_datetime(expires_at)
    await db.commit()
    await db.refresh(entry)
    return serialize_secret_entry(entry)


async def revoke_secret_value(
    db: AsyncSession,
    *,
    secret_id: str,
    revoked_by: str | None,
    note: str | None = None,
) -> dict[str, Any]:
    entry = await db.get(StoredSecret, secret_id)
    if entry is None:
        raise ValueError("Secret not found")
    previous_expires_at = ensure_utc(entry.expires_at)
    revoked_at = utc_now()
    entry.expires_at = revoked_at
    db.add(
        SecretRotationLog(
            id=str(uuid.uuid4()),
            secret_id=entry.id,
            action="revoked",
            rotated_by=revoked_by,
            previous_expires_at=previous_expires_at,
            new_expires_at=entry.expires_at,
            note=(note or "").strip() or None,
        )
    )
    await db.commit()
    await db.refresh(entry)
    return serialize_secret_entry(entry)


async def rotate_secret_value(
    db: AsyncSession,
    *,
    secret_id: str,
    rotated_by: str | None,
    value: str,
    expires_at: datetime | str | None = None,
    note: str | None = None,
) -> dict[str, Any]:
    entry = await db.get(StoredSecret, secret_id)
    if entry is None:
        raise ValueError("Secret not found")
    previous_expires_at = ensure_utc(entry.expires_at)
    entry.encrypted_value = encrypt_secret(value)
    entry.last_rotated_at = utc_now()
    entry.expires_at = _parse_optional_datetime(expires_at) if expires_at is not None else entry.expires_at
    db.add(
        SecretRotationLog(
            id=str(uuid.uuid4()),
            secret_id=entry.id,
            action="rotated",
            rotated_by=rotated_by,
            previous_expires_at=previous_expires_at,
            new_expires_at=entry.expires_at,
            note=(note or "").strip() or None,
        )
    )
    await db.commit()
    await db.refresh(entry)
    return serialize_secret_entry(entry)


async def _admin_user_ids(db: AsyncSession) -> list[str]:
    rows = await db.execute(
        select(User.id)
        .join(UserRole, UserRole.user_id == User.id)
        .join(Role, Role.id == UserRole.role_id)
        .where(Role.name == "admin", User.is_active)
    )
    return [row[0] for row in rows.all()]


async def process_secret_expiry_alerts(db: AsyncSession, *, alert_before_days: int = 30) -> dict[str, Any]:
    query_now = utc_now()
    now = utc_now_aware()
    threshold = query_now + timedelta(days=max(0, int(alert_before_days)))
    rows = (
        (
            await db.execute(
                select(StoredSecret)
                .where(
                    StoredSecret.expires_at.is_not(None),
                    StoredSecret.expires_at > query_now,
                    StoredSecret.expires_at <= threshold,
                )
                .order_by(StoredSecret.expires_at.asc())
                .limit(500)
            )
        )
        .scalars()
        .all()
    )
    admin_ids = await _admin_user_ids(db)
    notifications_sent = 0
    alerted = 0
    for entry in rows:
        existing_alert = (
            await db.execute(
                select(SecretRotationLog).where(
                    SecretRotationLog.secret_id == entry.id,
                    SecretRotationLog.action == "expiry_alert",
                    SecretRotationLog.new_expires_at == entry.expires_at,
                )
            )
        ).scalar_one_or_none()
        if existing_alert is not None:
            continue
        alerted += 1
        expires_at = ensure_utc(entry.expires_at)
        days_until_expiry = max(0, int((expires_at - now).total_seconds() // 86400)) if expires_at else None
        title = f"Secret expires soon: {entry.tool_name}.{entry.field_name}"
        body = (
            f"Stored secret '{entry.tool_name}.{entry.field_name}' expires in {days_until_expiry} days."
            if days_until_expiry is not None
            else f"Stored secret '{entry.tool_name}.{entry.field_name}' expires soon."
        )
        for user_id in admin_ids:
            created = await create_notification(
                db,
                user_id=user_id,
                notification_type="secret.expiring",
                title=title,
                body=body,
                link="/chat?" + urlencode({"area": "admin", "tab": "connectors", "connector": entry.tool_name}),
                payload={
                    "secret_id": entry.id,
                    "tool_name": entry.tool_name,
                    "field_name": entry.field_name,
                    "expires_at": expires_at.isoformat() if expires_at else None,
                },
            )
            if created is not None:
                notifications_sent += 1
        db.add(
            SecretRotationLog(
                id=str(uuid.uuid4()),
                secret_id=entry.id,
                action="expiry_alert",
                rotated_by=None,
                previous_expires_at=entry.expires_at,
                new_expires_at=entry.expires_at,
                note=f"alert_before_days={int(alert_before_days)}",
            )
        )
    await db.commit()
    return {
        "status": "ok",
        "expiring_secret_count": len(rows),
        "alerts_created": alerted,
        "notifications_sent": notifications_sent,
    }


class SecretExpiryWorker:
    def __init__(self, session_factory, interval_seconds: int = 21600, alert_before_days: int = 30) -> None:
        self._session_factory = session_factory
        self._interval_seconds = max(60, int(interval_seconds))
        self._alert_before_days = max(1, int(alert_before_days))
        self._task = None
        self._running = False

    async def start(self) -> None:
        if self._task is not None:
            return
        self._running = True
        self._task = asyncio.create_task(self._run(), name="secret-expiry-worker")

    async def stop(self) -> None:
        self._running = False
        if self._task is None:
            return
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        self._task = None

    def is_running(self) -> bool:
        return bool(self._running and self._task and not self._task.done())

    async def run_once(self) -> dict[str, Any]:
        started_at = utc_now()
        try:
            async with self._session_factory() as db:
                result = await process_secret_expiry_alerts(db, alert_before_days=self._alert_before_days)
            await record_background_worker_success(
                self._session_factory,
                worker_name="secret_expiry_worker",
                owner="secrets",
                started_at=started_at,
                result=result,
            )
            return result
        except Exception as exc:
            await record_background_worker_failure(
                self._session_factory,
                worker_name="secret_expiry_worker",
                owner="secrets",
                started_at=started_at,
                error=exc,
            )
            raise

    async def _run(self) -> None:
        while self._running:
            try:
                await self.run_once()
            except Exception:
                logger.exception("Secret expiry worker failed")
            await asyncio.sleep(self._interval_seconds)
