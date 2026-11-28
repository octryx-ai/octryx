"""The Teams plugin's dev mode, channel threads, follow-up metadata, mention policy and router thread keys."""

import pytest


@pytest.mark.asyncio
async def test_teams_plugin_dev_mode_is_blocked_outside_debug(monkeypatch):
    from app.config import Settings
    from app.plugins.channels.teams_plugin import TeamsPlugin

    settings = Settings(
        debug=False,
        jwt_secret="x" * 48,
        encryption_key="y" * 48,
        admin_default_password="S3cureAdminPass!",
        admin_email="admin@octryx.local",
        cors_allowed_origins="https://octryx.example",
        force_secure_auth_cookies=True,
    )
    monkeypatch.setattr("app.plugins.channels.teams_plugin.get_settings", lambda: settings)

    plugin = TeamsPlugin("msteams", {"dev_mode": True, "app_id": "", "app_password": ""})

    with pytest.raises(ValueError, match="Teams dev_mode is only allowed"):
        await plugin.initialize()


@pytest.mark.asyncio
async def test_teams_plugin_dev_mode_uses_mock_token_in_debug(monkeypatch):
    from app.config import Settings
    from app.plugins.channels.teams_plugin import TeamsPlugin

    settings = Settings(
        debug=True,
        jwt_secret="change-me-in-production",
        encryption_key="change-me-32-chars-long-secret!",
        admin_default_password="admin",
        admin_email="admin@localhost",
    )
    monkeypatch.setattr("app.plugins.channels.teams_plugin.get_settings", lambda: settings)

    plugin = TeamsPlugin("msteams", {"dev_mode": True, "app_id": "", "app_password": ""})

    await plugin.initialize()
    try:
        assert await plugin._ensure_token() == "dev-mock-token"
    finally:
        await plugin.shutdown()


@pytest.mark.asyncio
async def test_teams_plugin_creates_channel_thread_for_thread_target(monkeypatch):
    from app.plugins.channels.teams_plugin import TeamsPlugin

    requests = []

    class FakeResponse:
        def raise_for_status(self):
            return None

    class FakeClient:
        async def post(self, url, *, headers=None, json=None, data=None):
            requests.append({"url": url, "headers": headers, "json": json, "data": data})
            return FakeResponse()

    async def fake_ensure_token():
        return "token-1"

    plugin = TeamsPlugin(
        "msteams",
        {"app_id": "bot-1", "app_password": "secret", "__channel_name": "Octryx"},
    )
    plugin._http_client = FakeClient()
    monkeypatch.setattr(plugin, "_ensure_token", fake_ensure_token)

    ok = await plugin.send_message(
        "thread|https://smba.example/emea/|tenant-1|team-1|channel-1",
        "Approval needed",
    )

    assert ok is True
    assert len(requests) == 1
    request = requests[0]
    assert request["url"] == "https://smba.example/emea/v3/conversations"
    assert request["headers"] == {"Authorization": "Bearer token-1", "Content-Type": "application/json"}
    assert request["json"] == {
        "isGroup": True,
        "bot": {"id": "bot-1", "name": "Octryx"},
        "activity": {"type": "message", "text": "Approval needed"},
        "channelData": {
            "tenant": {"id": "tenant-1"},
            "team": {"id": "team-1"},
            "channel": {"id": "channel-1"},
            "teamsTeamId": "team-1",
            "teamsChannelId": "channel-1",
        },
    }


@pytest.mark.asyncio
async def test_teams_plugin_queues_channel_followup_metadata_without_mention():
    from app.plugins.channels.teams_plugin import TeamsPlugin

    plugin = TeamsPlugin("msteams", {"thread_followup_policy": "mention_once_per_thread"})

    await plugin.receive_webhook(
        {
            "type": "message",
            "text": "follow up",
            "from": {"id": "sender-1"},
            "conversation": {"conversationType": "channel", "id": "thread-1"},
            "serviceUrl": "https://smba.example/",
        }
    )

    message = await plugin.receive_message()
    assert message is not None
    assert message["content"] == "follow up"
    assert message["conversation_id"] == "thread-1"
    assert message["bot_mentioned"] is False


@pytest.mark.asyncio
async def test_teams_plugin_strict_policy_ignores_channel_message_without_mention():
    from app.plugins.channels.teams_plugin import TeamsPlugin

    plugin = TeamsPlugin("msteams", {"thread_followup_policy": "mention_every_message"})

    await plugin.receive_webhook(
        {
            "type": "message",
            "text": "follow up",
            "from": {"id": "sender-1"},
            "conversation": {"conversationType": "channel", "id": "thread-1"},
            "serviceUrl": "https://smba.example/",
        }
    )

    assert await plugin.receive_message() is None


def test_channel_router_uses_teams_thread_key_for_group_messages():
    from app.services.channel_router_runtime import ChannelMessageRouter

    router = ChannelMessageRouter()

    assert (
        router._build_channel_key(
            channel_id="2",
            plugin_id="msteams",
            sender_id="sender-1",
            channel_type="channel",
            conversation_id="thread-1",
        )
        == "2:teams-thread:thread-1"
    )
    assert (
        router._build_channel_key(
            channel_id="2",
            plugin_id="msteams",
            sender_id="sender-1",
            channel_type="personal",
            conversation_id="thread-1",
        )
        == "2:sender-1"
    )
