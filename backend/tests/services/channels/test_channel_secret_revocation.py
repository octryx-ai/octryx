from __future__ import annotations

import json
import secrets
import time

import pytest

from app.plugins import plugin_manager
from app.plugins.channels.slack_plugin import SlackPlugin
from app.services.channel_config import ChannelConfigService, runtime_sync
from app.services.channel_config.credentials import stored_config
from app.services.channel_webhook_auth.slack_signature import slack_signature
from app.services.secret import revoke_secret_value
from tests.services.channels.channel_webhook_auth_support import _post


@pytest.fixture
def slack_runtime(monkeypatch):
    # The process-wide plugin manager with empty state and a Slack start that makes no network call.
    monkeypatch.setattr(plugin_manager, "_plugins", {})
    monkeypatch.setattr(plugin_manager, "_applied", {})
    reloads: list[str] = []
    original_reload = plugin_manager.reload_channel

    async def reload_channel(channel_id, plugin_id, config):
        reloads.append(channel_id)
        return await original_reload(channel_id, plugin_id, config)

    async def initialize(self):
        return None

    monkeypatch.setattr(plugin_manager, "reload_channel", reload_channel)
    monkeypatch.setattr(SlackPlugin, "initialize", initialize)
    return reloads


def _session_factory(db):
    class _Session:
        async def __aenter__(self):
            return db

        async def __aexit__(self, *exc):
            return False

    return _Session


async def _slack_channel(db, signing_secret: str):
    created = await ChannelConfigService.create(
        db, plugin_id="slack", name="revocable-slack", project_id=None, enabled=True,
        config={"bot_token": secrets.token_urlsafe(24), "signing_secret": signing_secret})
    return str(created.id), stored_config(created.config)["signing_secret_secret_ref"]


async def _signed_post(client, channel_id: str, signing_secret: str):
    body = json.dumps({"type": "url_verification", "challenge": "c-7"}).encode()
    now = str(int(time.time()))
    headers = {"X-Slack-Request-Timestamp": now, "X-Slack-Signature": slack_signature(signing_secret, now, body)}
    return await _post(client, f"/api/v1/channels/slack/{channel_id}/webhook", body, headers)


@pytest.mark.asyncio
async def test_an_unchanged_secret_causes_no_reload(db, slack_runtime):
    channel_id, _ref = await _slack_channel(db, secrets.token_urlsafe(24))
    session = _session_factory(db)

    assert (await runtime_sync.reconcile_channels(session))["started"] == 1
    assert (await runtime_sync.reconcile_channels(session))["unchanged"] == 1
    assert slack_runtime == [channel_id]


@pytest.mark.asyncio
async def test_revoking_the_slack_signing_secret_unloads_the_plugin_and_refuses_the_webhook(
        client, db, slack_runtime):
    signing_secret = secrets.token_urlsafe(24)
    channel_id, ref = await _slack_channel(db, signing_secret)
    session = _session_factory(db)

    assert (await runtime_sync.reconcile_channels(session))["started"] == 1
    response = await _signed_post(client, channel_id, signing_secret)
    assert (response.status_code, response.json()) == (200, {"challenge": "c-7"})

    await revoke_secret_value(db, secret_id=ref, revoked_by=None, note="compromised")

    counts = await runtime_sync.reconcile_channels(session)
    assert plugin_manager.get_channel(channel_id) is None
    assert (await _signed_post(client, channel_id, signing_secret)).status_code == 404
    assert counts["blocked"] == 1
    # The revocation stays applied: later passes neither restart the plugin nor reload it again.
    assert (await runtime_sync.reconcile_channels(session))["unchanged"] == 1
    assert plugin_manager.get_channel(channel_id) is None
    assert slack_runtime == [channel_id, channel_id]
