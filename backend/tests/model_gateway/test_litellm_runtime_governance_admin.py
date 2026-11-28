"""The cross-runtime fallback mode written only through the validated admin surface: schema, service writer and admin route."""

from __future__ import annotations

from typing import Any

import pytest

from app.agent.runtime.retry_policy import build_runtime_retry_policy
from app.agent.runtime.runtime_fallback_policy import (
    RUNTIME_FALLBACK_MODE_ALL_RUNTIMES,
    RUNTIME_FALLBACK_MODE_FIRST_RUNTIME_ONLY,
)
from tests.model_gateway.conftest import backup_runtime

RUNTIME_SETTINGS_PATH = "/admin/chat/api/panel/runtime-settings"


async def _update_runtime_settings(db: Any, payload: dict[str, Any]) -> dict[str, Any]:
    from app.services.admin.provider import admin_runtime_service
    from app.services.control_plane_service import get_or_create_control_plane_config

    return await admin_runtime_service.update_runtime_settings(
        db,
        payload=payload,
        get_or_create_control_plane_config_func=get_or_create_control_plane_config,
        actor_user_id="fallback-mode-admin",
    )


async def test_runtime_fallback_mode_round_trips_through_the_admin_surface(db) -> None:
    from app.services.system_config import get_agent_runtime_settings

    updated = await _update_runtime_settings(
        db, {"runtime_fallback_mode": RUNTIME_FALLBACK_MODE_FIRST_RUNTIME_ONLY}
    )
    assert updated["runtime_fallback_mode"] == RUNTIME_FALLBACK_MODE_FIRST_RUNTIME_ONLY

    settings_payload = await get_agent_runtime_settings(db)
    assert settings_payload["runtime_fallback_mode"] == RUNTIME_FALLBACK_MODE_FIRST_RUNTIME_ONLY
    policy = build_runtime_retry_policy(settings_payload, runtimes=[backup_runtime()])
    assert policy["fallback_mode"] == RUNTIME_FALLBACK_MODE_FIRST_RUNTIME_ONLY
    assert policy["fallback_mode_source"] == "governed_setting"

    cleared = await _update_runtime_settings(db, {"runtime_fallback_mode": ""})
    assert cleared["runtime_fallback_mode"] == ""


async def test_runtime_fallback_mode_rejects_a_value_outside_the_enum(db) -> None:
    from fastapi import HTTPException

    from app.services.system_config import get_agent_runtime_settings

    await _update_runtime_settings(db, {"runtime_fallback_mode": RUNTIME_FALLBACK_MODE_ALL_RUNTIMES})

    with pytest.raises(HTTPException) as excinfo:
        await _update_runtime_settings(db, {"runtime_fallback_mode": "first_runtime_only_but_faster"})

    assert excinfo.value.status_code == 400
    assert "runtime_fallback_mode" in str(excinfo.value.detail)
    settings_payload = await get_agent_runtime_settings(db)
    assert settings_payload["runtime_fallback_mode"] == RUNTIME_FALLBACK_MODE_ALL_RUNTIMES


async def test_a_payload_without_the_key_is_a_no_op(db) -> None:
    from app.services.system_config import get_agent_runtime_settings

    await _update_runtime_settings(db, {"runtime_fallback_mode": RUNTIME_FALLBACK_MODE_FIRST_RUNTIME_ONLY})

    await _update_runtime_settings(db, {"approx_chars_per_token": 4})

    settings_payload = await get_agent_runtime_settings(db)
    assert settings_payload["runtime_fallback_mode"] == RUNTIME_FALLBACK_MODE_FIRST_RUNTIME_ONLY


async def test_the_admin_route_persists_and_exposes_the_governed_fallback_mode(admin_client) -> None:
    initial = await admin_client.get(RUNTIME_SETTINGS_PATH)
    assert initial.status_code == 200
    assert initial.json()["runtime_fallback_mode"] == ""

    written = await admin_client.put(
        RUNTIME_SETTINGS_PATH,
        json={"runtime_fallback_mode": RUNTIME_FALLBACK_MODE_FIRST_RUNTIME_ONLY},
    )
    assert written.status_code == 200
    assert written.json()["runtime_fallback_mode"] == RUNTIME_FALLBACK_MODE_FIRST_RUNTIME_ONLY

    reread = await admin_client.get(RUNTIME_SETTINGS_PATH)
    assert reread.status_code == 200
    assert reread.json()["runtime_fallback_mode"] == RUNTIME_FALLBACK_MODE_FIRST_RUNTIME_ONLY

    cleared = await admin_client.put(RUNTIME_SETTINGS_PATH, json={"runtime_fallback_mode": ""})
    assert cleared.status_code == 200
    assert cleared.json()["runtime_fallback_mode"] == ""
    assert (await admin_client.get(RUNTIME_SETTINGS_PATH)).json()["runtime_fallback_mode"] == ""


async def test_the_admin_route_rejects_a_fallback_mode_outside_the_enum(admin_client) -> None:
    await admin_client.put(
        RUNTIME_SETTINGS_PATH,
        json={"runtime_fallback_mode": RUNTIME_FALLBACK_MODE_ALL_RUNTIMES},
    )

    rejected = await admin_client.put(
        RUNTIME_SETTINGS_PATH,
        json={"runtime_fallback_mode": "first_runtime_only_but_faster"},
    )

    assert rejected.status_code == 400
    assert "runtime_fallback_mode" in str(rejected.json()["detail"])
    assert (await admin_client.get(RUNTIME_SETTINGS_PATH)).json()[
        "runtime_fallback_mode"
    ] == RUNTIME_FALLBACK_MODE_ALL_RUNTIMES
