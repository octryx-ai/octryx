"""Teams calling webhooks and Graph call notifications: audio WebSocket URIs, disabled calling and recording start."""

import asyncio

import pytest


@pytest.mark.asyncio
async def test_teams_calling_webhook_returns_audio_websocket_uri_for_enabled_call_proxy():
    from app.plugins.channels.teams_plugin import TeamsPlugin

    plugin = TeamsPlugin(
        "msteams",
        {
            "calling_enabled": True,
            "calling_mode": "call_proxy",
            "calling_public_ws_url": "wss://example.ngrok-free.dev/",
            "__channel_id": "2",
            "__channel_project_id": "project-1",
        },
    )

    result = await plugin.receive_webhook(
        {
            "type": "callStateChange",
            "value": {"state": "incoming", "id": "call/id with spaces"},
        }
    )

    from urllib.parse import parse_qs, urlsplit

    from app.services.teams_calling.audio_ws_token import consume_call_audio_token

    uri = urlsplit(result["audioWebSocketUri"])
    assert f"{uri.scheme}://{uri.netloc}{uri.path}" == (
        "wss://example.ngrok-free.dev/api/v1/teams/calls/call%2Fid%20with%20spaces/audio/ws"
    )
    query = parse_qs(uri.query)
    assert (query["project_id"], query["channel_id"]) == (["project-1"], ["2"])
    # The accepted call carries its own single-use audio WebSocket token.
    assert consume_call_audio_token("call/id with spaces", channel_id="2", project_id="project-1",
                                    token=query["token"][0]) is None


@pytest.mark.asyncio
async def test_teams_calling_webhook_ignores_call_when_calling_disabled():
    from app.plugins.channels.teams_plugin import TeamsPlugin

    plugin = TeamsPlugin(
        "msteams",
        {
            "calling_enabled": False,
            "calling_public_ws_url": "wss://example.ngrok-free.dev",
            "__channel_id": "2",
            "__channel_project_id": "project-1",
        },
    )

    result = await plugin.receive_webhook(
        {
            "type": "callStateChange",
            "value": {"state": "incoming", "id": "call-1"},
        }
    )

    assert result is None


@pytest.mark.asyncio
async def test_teams_calling_webhook_rejects_invalid_audio_ws_base():
    from app.plugins.channels.teams_plugin import TeamsPlugin

    plugin = TeamsPlugin(
        "msteams",
        {
            "calling_enabled": True,
            "calling_public_ws_url": "https://example.ngrok-free.dev",
            "__channel_id": "2",
            "__channel_project_id": "project-1",
        },
    )

    result = await plugin.receive_webhook(
        {
            "type": "callStateChange",
            "value": {"state": "incoming", "id": "call-1"},
        }
    )

    assert result is None


@pytest.mark.asyncio
async def test_teams_graph_calling_notifications_are_disabled_by_default():
    from app.plugins.channels.teams_plugin import TeamsPlugin

    plugin = TeamsPlugin(
        "msteams",
        {
            "calling_enabled": True,
            "calling_mode": "call_proxy",
            "__channel_id": "2",
            "__channel_project_id": "project-1",
        },
    )

    result = await plugin.receive_webhook(
        {
            "@odata.type": "#microsoft.graph.commsNotifications",
            "value": [
                {
                    "changeType": "created",
                    "resource": "/communications/calls/call-1",
                    "resourceData": {"state": "incoming"},
                }
            ],
        }
    )

    assert result == {"status": "ignored", "reason": "graph_recording_disabled"}
    assert plugin._active_calls == {}


@pytest.mark.asyncio
async def test_teams_graph_record_response_uses_supported_endpoint(monkeypatch):
    from app.plugins.channels.teams_plugin import TeamsPlugin

    class FakeResponse:
        status_code = 200
        text = '{"status":"running"}'

    class FakeHttpClient:
        def __init__(self):
            self.posts = []

        async def post(self, url, **kwargs):
            self.posts.append((url, kwargs))
            return FakeResponse()

    plugin = TeamsPlugin("msteams", {"calling_enabled": True, "calling_mode": "graph_recording"})
    fake_client = FakeHttpClient()
    plugin._http_client = fake_client

    async def fake_token():
        return "graph-token"

    monkeypatch.setattr(plugin, "_get_graph_token", fake_token)

    await plugin._start_record("call-1")

    # subscribeToTone + recordResponse = 2 posts
    assert len(fake_client.posts) == 2
    # First call: subscribeToTone
    url0, _ = fake_client.posts[0]
    assert url0 == "https://graph.microsoft.com/v1.0/communications/calls/call-1/subscribeToTone"
    # Second call: recordResponse
    url, kwargs = fake_client.posts[1]
    assert url == "https://graph.microsoft.com/v1.0/communications/calls/call-1/recordResponse"
    assert kwargs["headers"] == {"Authorization": "Bearer graph-token"}
    assert kwargs["json"]["bargeInAllowed"] is True
    assert kwargs["json"]["maxRecordDurationInSeconds"] == 10
    assert kwargs["json"]["maxSilenceTimeoutInSeconds"] == 3
    assert "prompts" not in kwargs["json"]
    assert "finalSilenceTimeoutInSeconds" not in kwargs["json"]


@pytest.mark.asyncio
async def test_teams_graph_established_starts_recording_once(monkeypatch):
    from app.plugins.channels.teams_plugin import TeamsPlugin

    plugin = TeamsPlugin(
        "msteams",
        {
            "calling_enabled": True,
            "calling_mode": "graph_recording",
            "__channel_id": "2",
            "__channel_project_id": "project-1",
        },
    )
    started = []

    async def fake_answer(call_id):
        return None

    async def fake_start_record(call_id):
        started.append(call_id)

    monkeypatch.setattr(plugin, "_answer_graph_call", fake_answer)
    monkeypatch.setattr(plugin, "_start_record", fake_start_record)

    payload = {
        "@odata.type": "#microsoft.graph.commsNotifications",
        "value": [
            {
                "changeType": "created",
                "resource": "/communications/calls/call-1",
                "resourceData": {"state": "incoming"},
            },
            {
                "changeType": "updated",
                "resource": "/communications/calls/call-1",
                "resourceData": {"state": "established"},
            },
            {
                "changeType": "updated",
                "resource": "/communications/calls/call-1",
                "resourceData": {"state": "established", "mediaState": {"audio": "active"}},
            },
        ],
    }

    result = await plugin.receive_webhook(payload)
    await asyncio.sleep(0)

    assert result == {"status": "accepted"}
    assert started == ["call-1"]
    assert plugin._active_calls["call-1"]["recording_started"] is True


def _graph_plugin(monkeypatch):
    from app.plugins.channels.teams_plugin import TeamsPlugin

    plugin = TeamsPlugin("msteams", {"calling_enabled": True, "calling_mode": "graph_recording", "__channel_id": "2",
                                     "__channel_project_id": "project-1"})
    started: list[str] = []

    async def fake_start_record(call_id):
        started.append(call_id)

    monkeypatch.setattr(plugin, "_start_record", fake_start_record)
    plugin._active_calls["call-1"] = {"channel_id": "2", "project_id": "project-1", "https_base": "https://bot.example.com",
                                      "caller_display_name": "", "caller_id": "u-1", "is_direct_call": True}
    return plugin, started


def _notification(resource_data: dict) -> dict:
    return {"@odata.type": "#microsoft.graph.commsNotifications", "value": [{"changeType": "updated", "resource": "/communications/calls/call-1",
                       "resourceData": resource_data}]}


@pytest.mark.asyncio
async def test_a_completed_recording_goes_to_the_worker_with_the_calls_facts(monkeypatch):
    from app.services.teams_calling import recording_processor

    plugin, started = _graph_plugin(monkeypatch)
    queued: list[dict] = []
    monkeypatch.setattr(recording_processor, "enqueue_recording", queued.append)
    result = await plugin.receive_webhook(_notification({
        "@odata.type": "#microsoft.graph.recordOperation", "status": "completed",
        "recordingLocation": "https://media.example.com/rec-1", "recordingAccessToken": "rec-token",
        "completionReason": "maxRecordDurationReached"}))
    await asyncio.sleep(0)
    assert result == {"status": "accepted"} and started == []
    assert queued == [{"call_id": "call-1", "recording_location": "https://media.example.com/rec-1",
                       "recording_access_token": "rec-token", "channel_id": "2", "project_id": "project-1",
                       "https_base": "https://bot.example.com", "caller_display_name": "", "caller_id": "u-1",
                       "is_direct_call": True, "completion_reason": "maxRecordDurationReached"}]


@pytest.mark.asyncio
async def test_a_recording_without_audio_or_a_failed_one_records_again(monkeypatch):
    plugin, started = _graph_plugin(monkeypatch)
    await plugin.receive_webhook(_notification({"@odata.type": "#microsoft.graph.recordOperation",
                                                "status": "completed", "completionReason": "operationCanceled"}))
    await plugin.receive_webhook(_notification({"@odata.type": "#microsoft.graph.recordOperation",
                                                "status": "failed"}))
    await plugin.receive_webhook(_notification({"@odata.type": "#microsoft.graph.playPromptOperation",
                                                "status": "completed"}))
    await asyncio.sleep(0)
    assert started == ["call-1", "call-1", "call-1"]


@pytest.mark.asyncio
async def test_a_terminated_call_is_forgotten(monkeypatch):
    from app.services.teams_calling import call_session_state

    plugin, _started = _graph_plugin(monkeypatch)
    closed: list[str] = []

    async def close(call_id):
        closed.append(call_id)

    monkeypatch.setattr(call_session_state, "close_call_db_session", close)
    await plugin.receive_webhook(_notification({"state": "terminated"}))
    await asyncio.sleep(0)
    assert "call-1" not in plugin._active_calls and closed == ["call-1"]
