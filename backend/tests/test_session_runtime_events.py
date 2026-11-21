import uuid

import pytest

from app.services.session.runtime_events import (
    EVENT_TOOL_CALL_BEGIN,
    EVENT_TOOL_CALL_END,
    EVENT_TURN_STARTED,
    RUNTIME_EVENT_SCHEMA_VERSION,
    publish_tool_call_begin,
    publish_tool_call_end,
    publish_turn_started,
)
from app.services.session.stream import session_stream_manager


class _FakeWebSocket:
    def __init__(self) -> None:
        self.accepted = False
        self.sent: list[dict] = []

    async def accept(self):
        self.accepted = True

    async def send_json(self, payload):
        self.sent.append(payload)


@pytest.mark.asyncio
async def test_runtime_events_publish_schema_versioned_turn_started():
    session_id = str(uuid.uuid4())
    websocket = _FakeWebSocket()

    await session_stream_manager.connect(session_id, websocket)
    try:
        await publish_turn_started(
            session_id=session_id,
            turn_id="req-1",
            user_message_id="msg-1",
            project_id="project-1",
            agent_type="research",
            runtime_target_id="runtime-1",
            thinking_level="light",
            request_id="req-1",
        )
    finally:
        await session_stream_manager.disconnect(session_id, websocket)
        await session_stream_manager.clear_run_tracking(session_id)

    event = websocket.sent[-1]
    assert event["type"] == EVENT_TURN_STARTED
    assert event["schemaVersion"] == RUNTIME_EVENT_SCHEMA_VERSION
    assert event["eventType"] == EVENT_TURN_STARTED
    assert event["turnId"] == "req-1"
    assert event["userMessageId"] == "msg-1"
    assert event["createdAt"].endswith("Z")


@pytest.mark.asyncio
async def test_tool_call_runtime_events_redact_sensitive_values_and_bound_payloads():
    session_id = str(uuid.uuid4())
    websocket = _FakeWebSocket()
    long_text = "x" * 2000

    await session_stream_manager.connect(session_id, websocket)
    try:
        await publish_tool_call_begin(
            session_id=session_id,
            turn_id="req-2",
            tool_call_id="call-2",
            tool_name="knowledge_search",
            parameters={
                "query": "Who is Alice Example?",
                "password": "must-not-stream",
                "nested": {"api_token": "also-secret", "text": long_text},
            },
            request_id="req-2",
        )
        await publish_tool_call_end(
            session_id=session_id,
            turn_id="req-2",
            tool_call_id="call-2",
            persisted_tool_call_id="artifact-2",
            tool_name="knowledge_search",
            status="success",
            duration_ms=123,
            artifact_id="artifact-2",
            result_preview={
                "summary": long_text,
                "secret": "must-not-stream",
                "items": list(range(40)),
            },
            cache={"status": "hit", "session_token": "must-not-stream"},
            request_id="req-2",
        )
    finally:
        await session_stream_manager.disconnect(session_id, websocket)
        await session_stream_manager.clear_run_tracking(session_id)

    begin = next(message for message in websocket.sent if message["type"] == EVENT_TOOL_CALL_BEGIN)
    end = next(message for message in websocket.sent if message["type"] == EVENT_TOOL_CALL_END)

    assert begin["parameters"]["query"] == "Who is Alice Example?"
    assert begin["parameters"]["password"] == "[redacted]"
    assert begin["parameters"]["nested"]["api_token"] == "[redacted]"
    assert begin["parameters"]["nested"]["text"].endswith("...[truncated]")
    assert end["persistedToolCallId"] == "artifact-2"
    assert end["durationMs"] == 123
    assert end["resultPreview"]["secret"] == "[redacted]"
    assert end["resultPreview"]["summary"].endswith("...[truncated]")
    assert end["resultPreview"]["items"][-1] == "[truncated]"
    assert end["cache"]["session_token"] == "[redacted]"
