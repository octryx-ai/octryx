from __future__ import annotations

import pytest

from app.services.system_config import (
    AGENT_RUNTIME_UNREACHABLE_RETRY_MAX_RETRIES_KEY,
    AGENT_RUNTIME_UNREACHABLE_RETRY_PAUSE_SECONDS_KEY,
    get_agent_runtime_settings,
    set_system_config_value,
)


@pytest.mark.asyncio
async def test_runtime_unreachable_retry_settings_are_loaded_from_system_config(db):
    await set_system_config_value(
        db,
        key=AGENT_RUNTIME_UNREACHABLE_RETRY_MAX_RETRIES_KEY,
        value="4",
    )
    await set_system_config_value(
        db,
        key=AGENT_RUNTIME_UNREACHABLE_RETRY_PAUSE_SECONDS_KEY,
        value="7",
    )
    await db.commit()

    runtime_settings = await get_agent_runtime_settings(db)

    assert runtime_settings["runtime_unreachable_retry_max_retries"] == 4
    assert runtime_settings["runtime_unreachable_retry_pause_seconds"] == 7


@pytest.mark.asyncio
async def test_execution_runtime_allow_host_fallback_defaults_to_false(db):
    runtime_settings = await get_agent_runtime_settings(db)

    assert runtime_settings["execution_runtime_allow_host_fallback"] is False
