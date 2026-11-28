"""Shared helpers for the test_channel_webhook_auth_* modules."""

from __future__ import annotations

import json
from typing import Any

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from app.plugins import plugin_manager
from app.plugins.channels.slack_plugin import SlackPlugin
from app.plugins.channels.teams_plugin import TeamsPlugin
from app.plugins.channels.telegram import TelegramPlugin
from app.services.channel_webhook_auth import gate
from app.services.channel_webhook_auth.signing_keys import StaticSigningKeySource

APP_ID = "11111111-2222-3333-4444-555555555555"


SLACK_SECRET = "slack-signing-secret-for-tests"


def _signing_key(kid: str) -> tuple[Any, dict[str, Any]]:
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(private.public_key()))
    public_jwk.update({"kid": kid, "use": "sig"})
    return private, public_jwk


BF_KEY, BF_JWK = _signing_key("bf-kid")


GRAPH_KEY, GRAPH_JWK = _signing_key("graph-kid")


class _Recorder:
    def __init__(self) -> None:
        self.payloads: list[dict] = []

    async def __call__(self, payload: dict) -> dict | None:
        self.payloads.append(payload)
        return None


@pytest.fixture
def channels(monkeypatch) -> dict[str, Any]:
    teams = TeamsPlugin("msteams", {"app_id": APP_ID, "__channel_id": "901"})
    slack = SlackPlugin("slack", {"bot_token": "xoxb-test", "signing_secret": SLACK_SECRET})
    telegram = TelegramPlugin("telegram", {"bot_token": "123:abc"})
    recorders = {}
    for channel_id, plugin in (("901", teams), ("902", slack), ("903", telegram)):
        recorders[channel_id] = _Recorder()
        plugin.receive_webhook = recorders[channel_id]
        monkeypatch.setitem(plugin_manager._plugins, channel_id, plugin)
    monkeypatch.setattr(
        gate,
        "default_key_sources",
        lambda: {
            "bot_framework": StaticSigningKeySource([BF_JWK]),
            "graph_calling": StaticSigningKeySource([GRAPH_JWK]),
        },
    )
    return {"teams": teams, "slack": slack, "recorders": recorders}


async def _post(client, url: str, body: bytes | dict, headers: dict | None = None):
    content = body if isinstance(body, bytes) else json.dumps(body).encode()
    request = client.build_request(
        "POST", url, content=content, headers={"Content-Type": "application/json", **(headers or {})}
    )
    request.headers.pop("origin", None)  # Microsoft and Slack send no browser Origin
    return await client.send(request)


def _code(response) -> str:
    return response.json()["detail"]["code"]
