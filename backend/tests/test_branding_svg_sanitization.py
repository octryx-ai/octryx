"""Focused tests for inline branding SVG sanitization."""

from __future__ import annotations

import json
import logging

import pytest

from app.config import get_settings
from app.web._helpers import chat_state as branding_module
from tests.conftest import ADMIN_PASSWORD


@pytest.fixture(autouse=True)
def _branding_feature_on(monkeypatch):
    monkeypatch.setattr(get_settings(), "branding_enabled", True)


def test_save_branding_config_sanitizes_safe_inline_svg(tmp_path, monkeypatch):
    branding_file = tmp_path / "branding.json"
    monkeypatch.setattr(branding_module, "_BRANDING_DATA_FILE", branding_file)

    result = branding_module._save_branding_config(
        {
            "app_name": "Octryx",
            "logo_url": "",
            "logo_svg": '<?xml version="1.0"?><svg viewBox="0 0 24 24"><path d="M2 2h20v20H2z" fill="#123456" /></svg>',
        }
    )

    assert result == {
        "app_name": "Octryx",
        "logo_url": "",
        "logo_svg": '<svg viewBox="0 0 24 24"><path d="M2 2h20v20H2z" fill="#123456" /></svg>',
        "enabled": True,
    }
    assert json.loads(branding_file.read_text()) == {k: v for k, v in result.items() if k != "enabled"}


def test_load_branding_config_drops_unsafe_inline_svg(tmp_path, monkeypatch, caplog):
    branding_file = tmp_path / "branding.json"
    branding_file.write_text(
        json.dumps(
            {
                "app_name": "Octryx",
                "logo_url": "",
                "logo_svg": '<svg viewBox="0 0 10 10"><script>alert(1)</script></svg>',
            }
        )
    )
    monkeypatch.setattr(branding_module, "_BRANDING_DATA_FILE", branding_file)

    with caplog.at_level(logging.WARNING):
        result = branding_module._load_branding_config()

    assert result == {"app_name": "Octryx", "logo_url": "", "logo_svg": "", "enabled": True}
    assert any("Dropping unsafe inline SVG branding" in message for message in caplog.messages)


@pytest.mark.asyncio
async def test_panel_update_branding_rejects_unsafe_inline_svg(client):
    login_response = await client.post("/admin/login", data={"username": "admin", "password": ADMIN_PASSWORD})
    assert login_response.status_code == 303

    response = await client.put(
        "/admin/chat/api/panel/branding",
        json={
            "app_name": "Octryx",
            "logo_url": "",
            "logo_svg": '<svg viewBox="0 0 10 10" onload="alert(1)"><circle cx="5" cy="5" r="4" /></svg>',
        },
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Inline SVG event handler attributes are not allowed"
