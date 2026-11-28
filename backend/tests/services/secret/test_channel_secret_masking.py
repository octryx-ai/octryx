from __future__ import annotations

import json

import pytest

from app.models import User
from app.models.integration.channel_config import ChannelConfig
from app.services.auth import hash_password
from app.services.channel_config.secret_fields import mask_channel_config
from app.services.secret import get_secret_value

TEAMS_SECRET = "teams-app-password-should-stay-server-side"


def test_mask_drops_declared_secrets_and_references_and_reports_has_value_from_the_reference():
    fields = [{"name": "smtp_password", "secret": True}, {"name": "imap_password", "secret": True},
              {"name": "smtp_host"}]
    masked, state = mask_channel_config(
        {"smtp_password_secret_ref": "secret-0001", "smtp_host": "mail.example.com", "bot_token_secret_ref": "secret-2"},
        fields,
    )

    assert masked == {"smtp_host": "mail.example.com"}
    assert state == {
        "bot_token": {"has_value": True},
        "imap_password": {"has_value": False},
        "smtp_password": {"has_value": True},
    }


@pytest.mark.asyncio
async def test_panel_never_returns_a_channel_secret_and_keeps_it_on_save(admin_client, db):
    created = await admin_client.post(
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
        await admin_client.get("/admin/chat/api/panel/channels"),
        await admin_client.get(f"/admin/chat/api/panel/channels/{channel_id}"),
    ):
        assert response.status_code == 200
        assert TEAMS_SECRET not in response.text

    # The editor sends the config it received (no secret): the stored password must survive.
    updated = await admin_client.put(
        f"/admin/chat/api/panel/channels/{channel_id}",
        json={"name": "Renamed bot", "enabled": False, "config": {"dev_mode": True, "app_id": "app-2"}},
    )
    assert updated.status_code == 200
    assert TEAMS_SECRET not in updated.text
    row = await db.get(ChannelConfig, channel_id)
    await db.refresh(row)
    assert TEAMS_SECRET not in row.config
    stored = json.loads(row.config)
    assert stored["app_id"] == "app-2" and "app_password" not in stored
    assert await get_secret_value(db, secret_id=stored["app_password_secret_ref"], purpose="test.read") == TEAMS_SECRET


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
