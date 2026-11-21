from starlette.requests import Request

import app.middleware.security.rate_limit as rate_limit


def _request(path: str) -> Request:
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": path,
            "query_string": b"",
            "headers": [],
            "client": ("127.0.0.1", 12345),
            "server": ("testserver", 80),
            "scheme": "http",
        }
    )


def test_api_rate_limit_disable_env_is_explicit(monkeypatch):
    request = _request("/api/v1/chat/bootstrap")

    monkeypatch.delenv("OCTRYX_DISABLE_API_RATE_LIMIT", raising=False)
    assert rate_limit._should_exempt(request) is False

    monkeypatch.setenv("OCTRYX_DISABLE_API_RATE_LIMIT", "1")
    assert rate_limit._should_exempt(request) is True
