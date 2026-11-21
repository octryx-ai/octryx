"""Request context and RLS middleware, the RLS context of get_db, observability counting and the JSON log formatter."""

import json
import logging
import sys

import pytest
from starlette.responses import Response

import app.db.core as database_module
import app.middleware.context.request_context as request_context_module
import app.middleware.security.row_level_security as rls_module
import app.middleware.telemetry.observability as observability_module
from app.services.observability.logging import JsonLogFormatter
from app.services.request_context import (
    get_current_rls_user_id,
    reset_current_rls_user_id,
    set_current_rls_user_id,
)
from tests.middleware_support import _build_request, _resolve_user_id


@pytest.mark.asyncio
async def test_request_context_middleware_sets_response_header_and_state():
    request = _build_request("/api/test", headers={"X-Request-ID": "req-123"})

    async def next_handler(inner_request):
        assert inner_request.state.request_id == "req-123"
        return Response("ok", status_code=200)

    response = await request_context_module.request_context_middleware(request, next_handler)

    assert response.status_code == 200
    assert response.headers["X-Request-ID"] == "req-123"


@pytest.mark.asyncio
async def test_rls_middleware_logs_failed_token_decode(monkeypatch, caplog):
    request = _build_request("/api/test", headers={"Authorization": "Bearer broken"})

    async def next_handler(_request):
        return Response("ok", status_code=200)

    monkeypatch.setattr(
        rls_module,
        "resolve_bearer_principal_user_id",
        lambda _db, _token: (_ for _ in ()).throw(RuntimeError("bad token")),
    )

    with caplog.at_level(logging.ERROR):
        response = await rls_module.rls_middleware(request, next_handler)

    assert response.status_code == 200
    assert "Failed to decode token for RLS middleware" in caplog.text


@pytest.mark.asyncio
async def test_rls_middleware_sets_and_resets_current_user_id(monkeypatch):
    request = _build_request("/api/test", headers={"Authorization": "Bearer valid"})
    observed = {}

    async def next_handler(_request):
        observed["user_id"] = get_current_rls_user_id()
        return Response("ok", status_code=200)

    monkeypatch.setattr(rls_module, "resolve_bearer_principal_user_id", _resolve_user_id)

    response = await rls_module.rls_middleware(request, next_handler)

    assert response.status_code == 200
    assert observed["user_id"] == "user-1"
    assert get_current_rls_user_id() is None


@pytest.mark.asyncio
async def test_get_db_sets_rls_context_on_same_session(monkeypatch):
    token = set_current_rls_user_id("user-rls")
    executed = []

    class FakeSession:
        async def execute(self, statement, params=None):
            executed.append((str(statement), params))

        async def commit(self):
            executed.append(("commit", None))

        async def rollback(self):
            executed.append(("rollback", None))

        async def close(self):
            executed.append(("close", None))

    class FakeSessionContext:
        async def __aenter__(self):
            return FakeSession()

        async def __aexit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(database_module, "_is_sqlite", False)
    monkeypatch.setattr(database_module, "async_session_factory", lambda: FakeSessionContext())

    try:
        agen = database_module.get_db()
        session = await agen.__anext__()
        assert session is not None
        with pytest.raises(StopAsyncIteration):
            await agen.__anext__()
    finally:
        reset_current_rls_user_id(token)
        monkeypatch.setattr(database_module, "_is_sqlite", True)

    assert executed[0][0].startswith("SELECT set_config('app.current_user_id'")
    assert executed[0][1] == {"uid": "user-rls"}
    assert ("commit", None) in executed


@pytest.mark.asyncio
async def test_observability_middleware_counts_in_memory_and_writes_no_row(monkeypatch):
    """O-D8: no ``api_request_metrics`` row per request; Health reads the in-memory window."""
    from app.services.observability.request_metrics import recent_request_summary, reset_recent_requests

    reset_recent_requests()
    request = _build_request("/api/v1/auth/whoami", method="GET", headers={"X-Request-ID": "req-metric"})

    async def next_handler(_request):
        return Response("ok", status_code=503)

    response = await observability_module.observability_middleware(request, next_handler)

    assert response.status_code == 503
    summary = recent_request_summary()
    assert (summary["requests"], summary["errors_5xx"]) == (1, 1)
    assert not hasattr(observability_module, "persist_api_request_metric")


def test_json_log_formatter_includes_request_id():
    formatter = JsonLogFormatter()
    record = logging.LogRecord(
        name="test.logger",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="hello observability",
        args=(),
        exc_info=None,
    )
    payload = json.loads(formatter.format(record))
    assert payload["logger"] == "test.logger"
    assert payload["message"] == "hello observability"
    assert "request_id" in payload


def test_json_log_formatter_redacts_messages_exceptions_and_metadata():
    formatter = JsonLogFormatter()
    record = logging.LogRecord(
        name="test.logger",
        level=logging.ERROR,
        pathname=__file__,
        lineno=1,
        msg="provider failed with token=raw-provider-token",
        args=(),
        exc_info=None,
    )
    record.api_key = "sk-log-secret"
    record.safe_component = "provider"
    try:
        raise RuntimeError("Authorization: Bearer provider-token-123456")
    except RuntimeError:
        record.exc_info = sys.exc_info()

    payload = json.loads(formatter.format(record))
    payload_text = json.dumps(payload)

    assert payload["metadata"]["safe_component"] == "provider"
    assert payload["metadata"]["api_key"] == "[redacted]"
    assert "raw-provider-token" not in payload_text
    assert "sk-log-secret" not in payload_text
    assert "provider-token-123456" not in payload_text
    assert "token=[redacted]" in payload["message"]
    assert "Bearer [redacted]" in payload["exception"]
