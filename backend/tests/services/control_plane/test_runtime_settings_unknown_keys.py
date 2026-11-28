"""The runtime settings update refuses a key it does not write, by name, instead of a silent no-op."""

import pytest

from app.services.admin.provider._admin_runtime_payload import WRITABLE_RUNTIME_SETTINGS

SETTINGS = "/admin/chat/api/panel/runtime-settings"


@pytest.mark.asyncio
async def test_an_unknown_key_is_refused_by_name_and_nothing_is_saved(admin_client):
    before = (await admin_client.get(SETTINGS)).json()["approx_chars_per_token"]

    response = await admin_client.put(SETTINGS, json={"approx_chars_per_token": 7, "stuck_loop_tool_repeat_threshold": 3,
                                                      "agent_default_model": "any"})

    assert response.status_code == 400, response.text
    assert response.json()["detail"] == {"code": "unknown_runtime_settings",
                                         "keys": ["agent_default_model", "stuck_loop_tool_repeat_threshold"]}
    assert (await admin_client.get(SETTINGS)).json()["approx_chars_per_token"] == before


@pytest.mark.asyncio
async def test_every_writable_setting_is_accepted(admin_client):
    current = (await admin_client.get(SETTINGS)).json()
    echo = {key: current[key] for key in WRITABLE_RUNTIME_SETTINGS if key in current and current[key] is not None}

    response = await admin_client.put(SETTINGS, json=echo)

    assert len(echo) >= 30
    assert response.status_code == 200, response.text
