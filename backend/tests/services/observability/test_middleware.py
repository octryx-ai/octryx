"""Request context middleware, observability counting and the JSON log formatter."""

import json
import logging
import sys

import pytest
from starlette.responses import Response

import app.middleware.context.request_context as request_context_module
import app.middleware.telemetry.observability as observability_module
from app.services.observability.logging import JsonLogFormatter
from tests.support.middleware_support import _build_request


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
async def test_observability_middleware_counts_in_memory_and_writes_no_row(monkeypatch):
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
