from datetime import UTC, datetime, timedelta, timezone
from types import SimpleNamespace

from app.services.session.api import _build_message_response, _build_session_response
from app.time_utils import utc_isoformat
from app.web._helpers.serialization import _serialize_timestamp


def test_utc_isoformat_marks_naive_values_as_utc():
    assert utc_isoformat(datetime(2026, 6, 1, 9, 27, 3)) == "2026-06-01T09:27:03Z"


def test_utc_isoformat_converts_aware_values_to_utc():
    value = datetime(2026, 6, 1, 11, 27, tzinfo=timezone(timedelta(hours=2)))

    assert utc_isoformat(value) == "2026-06-01T09:27:00Z"


def test_chat_timestamp_serializer_uses_explicit_utc_marker():
    assert _serialize_timestamp(datetime(2026, 6, 1, 9, 27, 3)) == "2026-06-01T09:27:03Z"


def test_session_api_serializes_timestamps_as_explicit_utc():
    session = SimpleNamespace(
        id="session-1",
        user_id="user-1",
        project_id=None,
        agent_type="diagnosis",
        status="active",
        started_at=datetime(2026, 6, 1, 9, 27, 3),
        ended_at=datetime(2026, 6, 1, 9, 30, 3, tzinfo=UTC),
    )
    message = SimpleNamespace(
        id="message-1",
        session_id="session-1",
        role="assistant",
        content="done",
        tool_calls=None,
        tool_results=None,
        model="model-1",
        tokens_in=1,
        tokens_out=2,
        cost=0,
        created_at=datetime(2026, 6, 1, 9, 28, 3),
    )

    session_payload = _build_session_response(session, message_count=1)
    message_payload = _build_message_response(message)

    assert session_payload.started_at == "2026-06-01T09:27:03Z"
    assert session_payload.ended_at == "2026-06-01T09:30:03Z"
    assert message_payload.created_at == "2026-06-01T09:28:03Z"
