"""Project configuration (TTS/STT and the panel config) is admin-only, and a partial update keeps unrelated keys."""

import pytest

from app.config import get_settings
from app.services.knowledge.projection.workspace_classification_values import PRESET_CLASSIFICATION


@pytest.fixture(autouse=True)
def _fresh_installation_default(monkeypatch):
    monkeypatch.setattr(get_settings(), "knowledge_default_data_classification", "")


def _assert_only_created_keys(config: dict) -> None:
    # A new Workspace carries its model grant (all cleared models), the Instance default level and nothing else.
    assert config["data_policy"] == {"classification": PRESET_CLASSIFICATION}
    created_keys = {"trace_capture", "model_policy", "agent_gateway_policy", "model_task_overrides", "data_policy"}
    assert {k: v for k, v in config.items() if k not in created_keys} == {}


@pytest.mark.asyncio
async def test_project_config_get_and_put_tts_stt(client, auth_headers):
    created = await client.post(
        "/api/v1/projects",
        headers=auth_headers,
        json={"name": "voice-config-project", "description": "TTS/STT test", "config": {}},
    )
    assert created.status_code == 200, created.text
    project = created.json()

    fetched = await client.get(f"/api/v1/projects/{project['id']}/config", headers=auth_headers)
    assert fetched.status_code == 200, fetched.text
    _assert_only_created_keys(fetched.json()["config"])

    saved = await client.put(
        f"/api/v1/projects/{project['id']}/config",
        headers=auth_headers,
        json={"tts": {"enabled": True, "default_voice": "nova", "default_speed": 1.2}},
    )
    assert saved.status_code == 200, saved.text
    data = saved.json()
    assert data["config"]["tts"]["enabled"] is True
    assert data["config"]["tts"]["default_voice"] == "nova"
    assert data["config"]["tts"]["default_speed"] == 1.2

    saved2 = await client.put(
        f"/api/v1/projects/{project['id']}/config",
        headers=auth_headers,
        json={"stt": {"enabled": True}},
    )
    assert saved2.status_code == 200, saved2.text
    data2 = saved2.json()
    assert data2["config"]["tts"]["enabled"] is True
    assert data2["config"]["tts"]["default_voice"] == "nova"
    assert data2["config"]["stt"]["enabled"] is True

    saved3 = await client.put(
        f"/api/v1/projects/{project['id']}/config",
        headers=auth_headers,
        json={"tts": {"default_voice": "echo"}},
    )
    assert saved3.status_code == 200, saved3.text
    data3 = saved3.json()
    assert data3["config"]["tts"]["enabled"] is True
    assert data3["config"]["tts"]["default_voice"] == "echo"
    assert data3["config"]["stt"]["enabled"] is True

    notfound = await client.put(
        "/api/v1/projects/nonexistent-id/config",
        headers=auth_headers,
        json={"tts": {"enabled": False}},
    )
    assert notfound.status_code == 404


@pytest.mark.asyncio
async def test_project_config_requires_admin(client, auth_headers):
    created = await client.post(
        "/api/v1/projects",
        headers=auth_headers,
        json={"name": "auth-test-project", "config": {}},
    )
    project = created.json()

    no_auth = await client.get(f"/api/v1/projects/{project['id']}/config")
    assert no_auth.status_code == 401


@pytest.mark.asyncio
async def test_panel_project_config_get_put(client, auth_headers):
    created = await client.post(
        "/api/v1/projects",
        headers=auth_headers,
        json={"name": "panel-config-test", "config": {}},
    )
    assert created.status_code == 200, created.text
    project = created.json()

    fetched = await client.get(f"/admin/chat/api/panel/projects/{project['id']}/config", headers=auth_headers)
    assert fetched.status_code == 200, f"GET failed: {fetched.status_code} {fetched.text}"
    _assert_only_created_keys(fetched.json()["config"])

    saved = await client.put(
        f"/admin/chat/api/panel/projects/{project['id']}/config",
        headers=auth_headers,
        json={"tts": {"enabled": True, "default_voice": "nova"}},
    )
    assert saved.status_code == 200, f"PUT failed: {saved.status_code} {saved.text}"
    data = saved.json()
    assert data["config"]["tts"]["enabled"] is True
    assert data["config"]["tts"]["default_voice"] == "nova"

    saved2 = await client.put(
        f"/admin/chat/api/panel/projects/{project['id']}/config",
        headers=auth_headers,
        json={"stt": {"enabled": True}},
    )
    assert saved2.status_code == 200, saved2.text
    data2 = saved2.json()
    assert data2["config"]["tts"]["enabled"] is True
    assert data2["config"]["stt"]["enabled"] is True

    notfound = await client.get("/admin/chat/api/panel/projects/nonexistent/config", headers=auth_headers)
    assert notfound.status_code == 404


@pytest.mark.asyncio
async def test_partial_config_update_keeps_unrelated_keys(client, auth_headers):
    created = await client.post(
        "/api/v1/projects",
        headers=auth_headers,
        json={
            "name": "partial-config-project",
            "config": {"owner": "platform", "tts": {"enabled": True, "default_voice": "nova"}},
        },
    )
    assert created.status_code == 200, created.text
    project_id = created.json()["id"]

    patched = await client.patch(
        f"/api/v1/projects/{project_id}",
        headers=auth_headers,
        json={"config": {"data_policy": {"classification": "internal"}}},
    )
    assert patched.status_code == 200, patched.text
    config = patched.json()["config"]
    assert config["owner"] == "platform"
    assert config["tts"] == {"enabled": True, "default_voice": "nova"}
    assert config["data_policy"] == {"classification": "internal"}

    put = await client.put(
        f"/api/v1/projects/{project_id}/config",
        headers=auth_headers,
        json={"tts": {"default_voice": "echo"}},
    )
    assert put.status_code == 200, put.text
    config = put.json()["config"]
    assert config["owner"] == "platform"
    assert config["tts"] == {"enabled": True, "default_voice": "echo"}
    assert config["data_policy"] == {"classification": "internal"}

    # PATCH now runs the key owners' validation too, and a refusal changes nothing.
    refused = await client.patch(
        f"/api/v1/projects/{project_id}",
        headers=auth_headers,
        json={"config": {"data_policy": {"classification": "not-a-level"}}},
    )
    assert refused.status_code == 400
    fetched = await client.get(f"/api/v1/projects/{project_id}/config", headers=auth_headers)
    assert fetched.json()["config"]["data_policy"] == {"classification": "internal"}
    assert fetched.json()["config"]["owner"] == "platform"
