"""Shared helpers for the test_agent_definition_execution_resolution_* modules."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.agent_definition_execution_states import AGENT_DEFINITION_EXECUTION_MODE_KEY
from app.services.system_config.values import set_system_config_value


async def _set_mode(db: AsyncSession, value: str | None) -> None:
    await set_system_config_value(
        db,
        key=AGENT_DEFINITION_EXECUTION_MODE_KEY,
        value=value,
        description="Agent definition execution mode (test)",
    )
    await db.flush()
