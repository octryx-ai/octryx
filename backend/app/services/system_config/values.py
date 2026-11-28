"""Core DB helpers for system configuration values."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.system_config.constants import (
    AGENT_DISK_HYGIENE_CORP_IDENTITY_CACHE_MIN_AGE_HOURS_KEY,
    AGENT_DISK_HYGIENE_OFFICE_IMPORT_STALE_MIN_AGE_HOURS_KEY,
    AGENT_WORKER_TRUST_DELTA_CORRECT_ESCALATION_KEY,
    AGENT_WORKER_TRUST_DELTA_FAILURE_KEY,
    AGENT_WORKER_TRUST_DELTA_HUMAN_APPROVED_KEY,
    AGENT_WORKER_TRUST_DELTA_HUMAN_OVERRIDDEN_KEY,
    AGENT_WORKER_TRUST_DELTA_SUCCESS_KEY,
    AGENT_WORKER_TRUST_DELTA_UNNECESSARY_ESCALATION_KEY,
    DEFAULT_DISK_HYGIENE_CORP_IDENTITY_CACHE_MIN_AGE_HOURS,
    DEFAULT_DISK_HYGIENE_OFFICE_IMPORT_STALE_MIN_AGE_HOURS,
)
from app.services.worker.policy import DEFAULT_TRUST_DELTAS

from ...models import SystemConfig

AGENT_DEFAULT_MODE_KEY = "agent.default_mode"


async def get_system_config_value(db: AsyncSession, key: str) -> str | None:
    row = (await db.execute(select(SystemConfig).where(SystemConfig.key == key))).scalar_one_or_none()
    if row is None:
        return None
    value = str(row.value or "").strip()
    return value or None


async def set_system_config_value(
    db: AsyncSession,
    *,
    key: str,
    value: str | None,
    description: str | None = None,
    updated_by: str | None = None,
) -> SystemConfig | None:
    row = (await db.execute(select(SystemConfig).where(SystemConfig.key == key))).scalar_one_or_none()
    normalized = str(value or "").strip()
    if not normalized:
        if row is not None:
            await db.delete(row)
            await db.flush()
        return None
    if row is None:
        row = SystemConfig(key=key, value=normalized, description=description)
        db.add(row)
    else:
        row.value = normalized
        if description is not None:
            row.description = description
    await db.flush()
    return row


async def get_agent_default_model(db: AsyncSession) -> str:
    """The platform default model: #1 of the platform order (empty when no runtime target is active)."""
    from ..model_selection.platform_order import order_targets

    targets = await order_targets(db)
    return str(targets[0].model_id) if targets else ""


async def get_agent_default_mode_key(db: AsyncSession) -> str:
    from ...agent.runtime_defaults import DEFAULT_AGENT_MODE_KEY

    raw_value = await get_system_config_value(db, AGENT_DEFAULT_MODE_KEY)
    normalized = str(raw_value or "").strip().lower()
    return normalized or DEFAULT_AGENT_MODE_KEY


async def get_disk_hygiene_corp_identity_cache_min_age_hours(db: AsyncSession) -> int:
    return bounded_int(
        await get_system_config_value(db, AGENT_DISK_HYGIENE_CORP_IDENTITY_CACHE_MIN_AGE_HOURS_KEY),
        default=DEFAULT_DISK_HYGIENE_CORP_IDENTITY_CACHE_MIN_AGE_HOURS,
        minimum=1,
        maximum=24 * 30,
    )


async def get_disk_hygiene_office_import_stale_min_age_hours(db: AsyncSession) -> int:
    return bounded_int(
        await get_system_config_value(db, AGENT_DISK_HYGIENE_OFFICE_IMPORT_STALE_MIN_AGE_HOURS_KEY),
        default=DEFAULT_DISK_HYGIENE_OFFICE_IMPORT_STALE_MIN_AGE_HOURS,
        minimum=1,
        maximum=24 * 30,
    )


async def get_worker_trust_deltas(db: AsyncSession) -> dict[str, float]:
    return {
        "success": bounded_float(
            await get_system_config_value(db, AGENT_WORKER_TRUST_DELTA_SUCCESS_KEY),
            default=DEFAULT_TRUST_DELTAS["success"],
            minimum=-1.0,
            maximum=1.0,
        ),
        "failure": bounded_float(
            await get_system_config_value(db, AGENT_WORKER_TRUST_DELTA_FAILURE_KEY),
            default=DEFAULT_TRUST_DELTAS["failure"],
            minimum=-1.0,
            maximum=1.0,
        ),
        "unnecessary_escalation": bounded_float(
            await get_system_config_value(db, AGENT_WORKER_TRUST_DELTA_UNNECESSARY_ESCALATION_KEY),
            default=DEFAULT_TRUST_DELTAS["unnecessary_escalation"],
            minimum=-1.0,
            maximum=1.0,
        ),
        "correct_escalation": bounded_float(
            await get_system_config_value(db, AGENT_WORKER_TRUST_DELTA_CORRECT_ESCALATION_KEY),
            default=DEFAULT_TRUST_DELTAS["correct_escalation"],
            minimum=-1.0,
            maximum=1.0,
        ),
        "human_overridden": bounded_float(
            await get_system_config_value(db, AGENT_WORKER_TRUST_DELTA_HUMAN_OVERRIDDEN_KEY),
            default=DEFAULT_TRUST_DELTAS["human_overridden"],
            minimum=-1.0,
            maximum=1.0,
        ),
        "human_approved": bounded_float(
            await get_system_config_value(db, AGENT_WORKER_TRUST_DELTA_HUMAN_APPROVED_KEY),
            default=DEFAULT_TRUST_DELTAS["human_approved"],
            minimum=-1.0,
            maximum=1.0,
        ),
    }


def bounded_int(
    raw_value: str | None,
    *,
    default: int,
    minimum: int,
    maximum: int,
) -> int:
    try:
        parsed = int(str(raw_value or "").strip())
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(parsed, maximum))


def bounded_float(
    raw_value: str | None,
    *,
    default: float,
    minimum: float,
    maximum: float,
) -> float:
    try:
        parsed = float(str(raw_value or "").strip())
    except (TypeError, ValueError):
        parsed = default
    return round(max(minimum, min(parsed, maximum)), 4)
