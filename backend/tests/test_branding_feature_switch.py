"""Branding is a platform feature switch: off by default, server config only."""

from __future__ import annotations

import json

import pytest

import app.web._helpers.chat_state as chat_state_module
from app.config import Settings, get_settings
from tests.conftest import ADMIN_PASSWORD

_STORED = {"app_name": "Acme", "logo_url": "https://acme.example/logo.svg", "logo_svg": ""}
_DEFAULTS = {
    "app_name": "Octryx",
    "logo_url": "/chat/static/chat/message-logo.svg",
    "logo_svg": "",
    "enabled": False,
}


@pytest.fixture
def stored_branding(tmp_path, monkeypatch):
    branding_file = tmp_path / "branding.json"
    branding_file.write_text(json.dumps(_STORED))
    monkeypatch.setattr(chat_state_module, "_BRANDING_DATA_FILE", branding_file)
    return branding_file


async def _login(client):
    response = await client.post("/admin/login", data={"username": "admin", "password": ADMIN_PASSWORD})
    assert response.status_code == 303


def test_branding_is_off_by_default():
    assert Settings.model_fields["branding_enabled"].default is False


@pytest.mark.asyncio
async def test_disabled_branding_reads_defaults_and_refuses_writes(client, stored_branding, monkeypatch):
    monkeypatch.setattr(get_settings(), "branding_enabled", False)
    await _login(client)

    read = await client.get("/admin/chat/api/panel/branding")
    assert read.status_code == 200
    assert read.json() == _DEFAULTS

    write = await client.put("/admin/chat/api/panel/branding", json={"app_name": "Other", "logo_url": "", "logo_svg": ""})
    assert write.status_code == 409
    assert write.json()["detail"]["code"] == "branding_disabled"
    # Stored branding stays untouched, just not applied.
    assert json.loads(stored_branding.read_text()) == _STORED


@pytest.mark.asyncio
async def test_enabled_branding_applies_stored_config(client, stored_branding, monkeypatch):
    monkeypatch.setattr(get_settings(), "branding_enabled", True)
    await _login(client)

    read = await client.get("/admin/chat/api/panel/branding")
    assert read.status_code == 200
    assert read.json() == {**_STORED, "enabled": True}
