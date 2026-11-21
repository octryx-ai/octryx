"""Admin write path for the governed cross-runtime fallback mode.

The mode is a closed enum (``all_runtimes`` / ``first_runtime_only``). This
module is the only writer, and it rejects anything outside that set with a 400
instead of storing it: a stored unknown value would later have to be interpreted
at read time, and every interpretation is either permissive (wrong) or invisible
(worse). Clearing the value is explicit and supported — it restores the
per-driver default, which keeps a governed model-gateway chain on
``first_runtime_only``.
"""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from ....agent.core.runtime.runtime_fallback_policy import RUNTIME_FALLBACK_MODES
from ...system_config import AGENT_RUNTIME_FALLBACK_MODE_KEY, set_system_config_value

SETTING_KEY = "runtime_fallback_mode"

_SETTING_DESCRIPTION = (
    "Cross-runtime fallback policy for agent turns. 'all_runtimes' keeps the full "
    "runtime chain, 'first_runtime_only' turns the first runtime's exhaustion into a "
    "final error. Unset applies the per-driver default."
)


async def apply_runtime_fallback_mode_setting(db: AsyncSession, *, payload: dict[str, Any]) -> None:
    """Persist the governed fallback mode, or reject an unknown value."""

    if SETTING_KEY not in payload:
        return
    raw_value = payload.get(SETTING_KEY)
    if raw_value is None or (isinstance(raw_value, str) and not raw_value.strip()):
        await set_system_config_value(db, key=AGENT_RUNTIME_FALLBACK_MODE_KEY, value=None)
        return
    mode = str(raw_value).strip().lower()
    if mode not in RUNTIME_FALLBACK_MODES:
        raise HTTPException(
            status_code=400,
            detail=(
                f"{SETTING_KEY} must be one of: " + ", ".join(sorted(RUNTIME_FALLBACK_MODES))
            ),
        )
    await set_system_config_value(
        db,
        key=AGENT_RUNTIME_FALLBACK_MODE_KEY,
        value=mode,
        description=_SETTING_DESCRIPTION,
    )


__all__ = ["SETTING_KEY", "apply_runtime_fallback_mode_setting"]
