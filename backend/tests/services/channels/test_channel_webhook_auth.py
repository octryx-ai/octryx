"""Contract: every inbound channel webhook is deny-by-default (Teams JWTs, Slack signatures, no scheme for
other channels, refused before the body is parsed, no development exception outside DEBUG)."""

from __future__ import annotations

import json
import time

import jwt
import pytest

from app.services.channel_webhook_auth.slack_signature import slack_signature
from tests.services.channels.channel_webhook_auth_support import (  # noqa: F401
    APP_ID,
    BF_KEY,
    GRAPH_KEY,
    SLACK_SECRET,
    _code,
    _post,
    _signing_key,
    channels,
)

SERVICE_URL = "https://smba.trafficmanager.net/emea/"


FOREIGN_KEY, _ = _signing_key("bf-kid")


def _token(key, kid: str, **overrides) -> str:
    now = int(time.time())
    claims = {
        "iss": "https://api.botframework.com",
        "aud": APP_ID,
        "exp": now + 600,
        "nbf": now - 60,
        "serviceUrl": SERVICE_URL,
    }
    claims.update(overrides)
    return jwt.encode({k: v for k, v in claims.items() if v is not None}, key, algorithm="RS256", headers={"kid": kid})


@pytest.mark.asyncio
async def test_teams_webhook_accepts_only_a_verified_bound_microsoft_token(client, channels):  # noqa: F811
    url = "/api/v1/channels/msteams/901/webhook"
    activity = {"type": "message", "text": "hi", "serviceUrl": SERVICE_URL, "channelId": "msteams"}
    notification = {"@odata.type": "#microsoft.graph.commsNotifications", "value": []}
    bearer = lambda token: {"Authorization": f"Bearer {token}"}  # noqa: E731
    refused = {
        "missing header": ({}, activity, "channel_webhook_unauthenticated"),
        "not a bearer": ({"Authorization": "Basic abc"}, activity, "channel_webhook_unauthenticated"),
        "foreign signature": (bearer(_token(FOREIGN_KEY, "bf-kid")), activity, "channel_webhook_signature_invalid"),
        "unknown key": (bearer(_token(BF_KEY, "other-kid")), activity, "channel_webhook_signature_invalid"),
        "expired": (
            bearer(_token(BF_KEY, "bf-kid", exp=int(time.time()) - 3600, nbf=int(time.time()) - 7200)),
            activity,
            "channel_webhook_signature_invalid",
        ),
        "wrong audience": (
            bearer(_token(BF_KEY, "bf-kid", aud="another-app")),
            activity,
            "channel_webhook_signature_invalid",
        ),
        "wrong issuer": (
            bearer(_token(BF_KEY, "bf-kid", iss="https://evil.example")),
            activity,
            "channel_webhook_signature_invalid",
        ),
        "serviceUrl mismatch": (
            bearer(_token(BF_KEY, "bf-kid", serviceUrl="https://attacker.example/")),
            activity,
            "channel_webhook_signature_invalid",
        ),
        "graph token on a chat activity": (
            bearer(_token(GRAPH_KEY, "graph-kid")),
            activity,
            "channel_webhook_signature_invalid",
        ),
        "bot token on a calling notification": (
            bearer(_token(BF_KEY, "bf-kid")),
            notification,
            "channel_webhook_signature_invalid",
        ),
    }
    for case, (headers, body, state) in refused.items():
        response = await _post(client, url, body, headers)
        assert (response.status_code, _code(response)) == (401, state), case
    assert channels["recorders"]["901"].payloads == []

    assert (await _post(client, url, activity, bearer(_token(BF_KEY, "bf-kid")))).status_code == 200
    graph_token = _token(GRAPH_KEY, "graph-kid", iss="https://graph.microsoft.com", serviceUrl=None)
    assert (await _post(client, url, notification, bearer(graph_token))).status_code == 200
    assert channels["recorders"]["901"].payloads == [activity, notification]

    channels["teams"].app_id = ""
    response = await _post(client, url, activity, bearer(_token(BF_KEY, "bf-kid")))
    assert (response.status_code, _code(response)) == (403, "channel_webhook_auth_not_configured")
    assert len(channels["recorders"]["901"].payloads) == 2


@pytest.mark.asyncio
async def test_slack_webhook_accepts_only_a_fresh_valid_signature(client, channels):  # noqa: F811
    url = "/api/v1/channels/slack/902/webhook"
    body = json.dumps({"type": "url_verification", "challenge": "c-1"}).encode()
    now = str(int(time.time()))
    stale = str(int(time.time()) - 301)

    def signed(timestamp: str, secret: str = SLACK_SECRET) -> dict:
        return {"X-Slack-Request-Timestamp": timestamp, "X-Slack-Signature": slack_signature(secret, timestamp, body)}

    refused = {
        "missing headers": ({}, "channel_webhook_unauthenticated"),
        "timestamp only": ({"X-Slack-Request-Timestamp": now}, "channel_webhook_unauthenticated"),
        "wrong signature": (signed(now, secret="another-secret"), "channel_webhook_signature_invalid"),
        "stale timestamp": (signed(stale), "channel_webhook_signature_invalid"),
    }
    for case, (headers, state) in refused.items():
        response = await _post(client, url, body, headers)
        assert (response.status_code, _code(response)) == (401, state), case
    assert channels["recorders"]["902"].payloads == []

    response = await _post(client, url, body, signed(now))
    assert (response.status_code, response.json()) == (200, {"challenge": "c-1"})
    assert channels["recorders"]["902"].payloads == [json.loads(body)]

    channels["slack"].signing_secret = ""
    response = await _post(client, url, body, signed(now))
    assert (response.status_code, _code(response)) == (403, "channel_webhook_auth_not_configured")


@pytest.mark.asyncio
async def test_other_channel_types_are_refused_without_their_scheme(client, channels):  # noqa: F811
    response = await _post(client, "/api/v1/channels/903/webhook", {"message": {"text": "hi"}})
    assert (response.status_code, _code(response)) == (403, "channel_webhook_auth_not_configured")
    assert channels["recorders"]["903"].payloads == []
