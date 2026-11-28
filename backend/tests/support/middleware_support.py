"""Shared helpers for the test_middleware_* modules."""

from starlette.requests import Request


async def _resolve_user_id(_db, _token):
    return "user-1"


def _build_request(path: str, method: str = "GET", headers: dict[str, str] | None = None) -> Request:
    raw_headers = [(key.lower().encode("latin-1"), value.encode("latin-1")) for key, value in (headers or {}).items()]
    scope = {
        "type": "http",
        "method": method,
        "path": path,
        "headers": raw_headers,
        "client": ("127.0.0.1", 12345),
        "scheme": "http",
        "server": ("testserver", 80),
        "query_string": b"",
    }
    return Request(scope)
