"""Channel secrets are write-only.

The browser never receives a Teams app password, Slack token or SMTP password: the panel returns
``secret_fields[key].has_value`` instead, and a save that omits the secret keeps the stored one.
"""

from __future__ import annotations

import json

import pytest

from app.models import User
from app.models.integration.channel_config import ChannelConfig
from app.services.auth import hash_password
from app.services.channel_config.secret_fields import mask_channel_config, merge_channel_secrets
from tests.conftest import ADMIN_PASSWORD

TEAMS_SECRET = "teams-app-password-should-stay-server-side"


def test_mask_drops_declared_and_secret_named_values():
    fields = [{"name": "smtp_password", "secret": True}, {"name": "smtp_host"}]
    masked, state = mask_channel_config(
        {"smtp_password": "pw", "smtp_host": "mail.example.com", "bot_token": "xoxb-1", "imap_password": ""},
        fields,
    )

    assert masked == {"smtp_host": "mail.example.com"}
    assert state == {
        "bot_token": {"has_value": True},
        "imap_password": {"has_value": False},
        "smtp_password": {"has_value": True},
    }


def test_merge_keeps_stored_secret_unless_a_new_one_is_sent():
    fields = [{"name": "bot_token", "secret": True}]
    stored = {"bot_token": "old", "channel": "a"}

    assert merge_channel_secrets({"channel": "b"}, stored, fields) == {"channel": "b", "bot_token": "old"}
    assert merge_channel_secrets({"bot_token": ""}, stored, fields) == {"bot_token": "old"}
    assert merge_channel_secrets({"bot_token": "new"}, stored, fields) == {"bot_token": "new"}


@pytest.mark.asyncio
async def test_panel_never_returns_a_channel_secret_and_keeps_it_on_save(client, db):
    login = await client.post("/admin/login", data={"username": "admin", "password": ADMIN_PASSWORD})
    assert login.status_code == 303

    created = await client.post(
        "/admin/chat/api/panel/channels",
        json={
            "plugin_id": "msteams",
            "name": "Secret Teams Bot",
            "enabled": False,
            "config": {"dev_mode": True, "app_id": "app-1", "app_password": TEAMS_SECRET},
        },
    )
    assert created.status_code == 200
    assert TEAMS_SECRET not in created.text
    assert created.json()["secret_fields"]["app_password"] == {"has_value": True}
    channel_id = created.json()["id"]

    for response in (
        await client.get("/admin/chat/api/panel/channels"),
        await client.get(f"/admin/chat/api/panel/channels/{channel_id}"),
    ):
        assert response.status_code == 200
        assert TEAMS_SECRET not in response.text

    # The editor sends the config it received (no secret): the stored password must survive.
    updated = await client.put(
        f"/admin/chat/api/panel/channels/{channel_id}",
        json={"name": "Renamed bot", "enabled": False, "config": {"dev_mode": True, "app_id": "app-2"}},
    )
    assert updated.status_code == 200
    assert TEAMS_SECRET not in updated.text
    row = await db.get(ChannelConfig, channel_id)
    await db.refresh(row)
    stored = json.loads(row.config) if isinstance(row.config, str) else row.config
    assert stored["app_password"] == TEAMS_SECRET
    assert stored["app_id"] == "app-2"


@pytest.mark.asyncio
async def test_member_cannot_read_channel_configs(client, db):
    db.add(
        User(
            username="channel-member",
            email="channel-member@example.com",
            password_hash=hash_password("testpass123"),
            is_active=True,
        )
    )
    await db.commit()
    login = await client.post("/admin/login", data={"username": "channel-member", "password": "testpass123"})
    assert login.status_code == 303

    denied = await client.get("/admin/chat/api/panel/channels")

    assert denied.status_code == 403
