"""Instance settings and status of the policy engine for the admin API.

- Mode ``off | shadow | enforce`` (``runtime.MODE_CONFIG_KEY``), audited on every change. Selecting ``shadow``
  starts the shadow window (``enforce.SHADOW_SINCE_CONFIG_KEY``) and resets the dropped-record counter;
  ``enforce`` is accepted only when ``enforce.enforce_readiness`` is ready (else
  ``policy_engine_enforce_not_ready`` with the reasons).
- Settings: the enforce window in hours (1..720) and the decision-log retention in days (1..365), audited.
- Status: mode, engine availability, schema version, published custom version (with the shadow fallback when it
  no longer parses), the baseline digest, the per-point decision and fallback counters, the shadow latency (and the
  draft-shadow evaluation's own latency) and the decision-log buffer.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ...models import AuditLog
from ...time_utils import utc_now
from ..system_config.values import set_system_config_value
from .baseline import load_baseline
from .decision_log import (
    MAX_RETENTION_DAYS,
    RETENTION_CONFIG_KEY,
    dropped_records,
    pending_records,
    reset_dropped_records,
    retention_days,
)
from .enforce import (
    MAX_WINDOW_HOURS,
    SHADOW_SINCE_CONFIG_KEY,
    WINDOW_CONFIG_KEY,
    enforce_readiness,
    shadow_since,
    window_hours,
)
from .engine import PolicyEngineUnavailableError, compiled_schema
from .runtime import MODE_CONFIG_KEY, MODE_ENFORCE, MODE_SHADOW, MODES, published_version, refresh_policy_runtime
from .schema import SCHEMA_VERSION
from .shadow import custom_fallback_counters, decision_counters, draft_latency_summary, latency_summary

AUDIT_MODE_UPDATED = "policy_engine.mode_updated"
AUDIT_SETTINGS_UPDATED = "policy_engine.settings_updated"
ERROR_MODE_INVALID = "policy_engine_mode_invalid"
ERROR_ENFORCE_NOT_READY = "policy_engine_enforce_not_ready"
ERROR_SETTING_INVALID = "policy_engine_setting_invalid"


class PolicyEngineSettingError(ValueError):
    def __init__(self, code: str, status: int = 422, **details: Any) -> None:
        super().__init__(code)
        self.code = code
        self.status = status
        self.details = details


async def set_mode(db: AsyncSession, *, mode: Any, actor_id: str) -> str:
    """Store the instance mode and audit it; flushes. The caller commits, then refreshes the runtime."""
    value = str(mode or "").strip().lower()
    if value not in MODES:
        raise PolicyEngineSettingError(ERROR_MODE_INVALID)
    runtime = await refresh_policy_runtime(db)
    previous = runtime.mode
    if value == MODE_ENFORCE and previous != MODE_ENFORCE:
        readiness = await enforce_readiness(db, runtime)
        if not readiness["ready"]:
            raise PolicyEngineSettingError(ERROR_ENFORCE_NOT_READY, 409, reasons=readiness["reasons"])
    await _store(db, MODE_CONFIG_KEY, value, "Cedar policy engine mode", actor_id)
    if value == MODE_SHADOW and (previous != MODE_SHADOW or await shadow_since(db) is None):
        await _store(db, SHADOW_SINCE_CONFIG_KEY, utc_now().isoformat(), "Cedar shadow window start", actor_id)
        reset_dropped_records()
    db.add(AuditLog(user_id=actor_id, action=AUDIT_MODE_UPDATED, resource_type="system_config",
                    resource_id=MODE_CONFIG_KEY, details={"previous": previous, "mode": value}))
    await db.flush()
    return value


async def _store(db: AsyncSession, key: str, value: str, description: str, actor_id: str) -> None:
    await set_system_config_value(db, key=key, value=value, description=description, updated_by=actor_id,
                                  record_prompt_revision=False)


_SETTINGS = {
    "enforce_window_hours": (WINDOW_CONFIG_KEY, 1, MAX_WINDOW_HOURS, "Cedar enforce window (hours)"),
    "decision_log_retention_days": (RETENTION_CONFIG_KEY, 1, MAX_RETENTION_DAYS, "Cedar decision log retention"),
}


async def set_settings(db: AsyncSession, *, values: Any, actor_id: str) -> dict[str, int]:
    """Store the window and the retention (each optional, whole numbers in range); flushes."""
    if not isinstance(values, dict) or not values or set(values) - set(_SETTINGS):
        raise PolicyEngineSettingError(ERROR_SETTING_INVALID)
    saved: dict[str, int] = {}
    for name, value in values.items():
        key, low, high, description = _SETTINGS[name]
        if type(value) is not int or not low <= value <= high:
            raise PolicyEngineSettingError(ERROR_SETTING_INVALID, field=name)
        await _store(db, key, str(value), description, actor_id)
        saved[name] = value
    db.add(AuditLog(user_id=actor_id, action=AUDIT_SETTINGS_UPDATED, resource_type="system_config",
                    resource_id="policy_engine", details=saved))
    await db.flush()
    return {"enforce_window_hours": await window_hours(db), "decision_log_retention_days": await retention_days(db)}


def engine_available() -> bool:
    try:
        compiled_schema()
    except PolicyEngineUnavailableError:
        return False
    return True


async def engine_status(db: AsyncSession) -> dict[str, Any]:
    runtime = await refresh_policy_runtime(db)
    published = await published_version(db)
    baseline = await load_baseline(db)
    return {
        "mode": runtime.mode,
        "modes": list(MODES),
        "engine": {"available": engine_available(), "library": "cedarpy", "schema_version": SCHEMA_VERSION},
        "custom": {
            "version": published.version if published is not None else None,
            "digest": published.digest if published is not None else None,
            "valid": not runtime.custom_invalid,
            # An unparseable published set is not applied: its policies fall back to shadow (``runtime``).
            "fallback": MODE_SHADOW if runtime.custom_invalid else None,
        },
        "baseline": {"digest": baseline.digest, "workspaces": baseline.workspaces,
                     "matrix_state": baseline.matrix_state},
        "counters": decision_counters(),
        "custom_fallbacks": custom_fallback_counters(),
        "latency": latency_summary(),
        "draft_latency": draft_latency_summary(),
        "decision_log": {"pending": pending_records(), "dropped": dropped_records(),
                         "retention_days": await retention_days(db)},
        "enforce": await enforce_readiness(db, runtime),
    }


__all__ = [
    "AUDIT_MODE_UPDATED",
    "AUDIT_SETTINGS_UPDATED",
    "ERROR_ENFORCE_NOT_READY",
    "ERROR_MODE_INVALID",
    "ERROR_SETTING_INVALID",
    "PolicyEngineSettingError",
    "engine_available",
    "engine_status",
    "set_mode",
    "set_settings",
]
