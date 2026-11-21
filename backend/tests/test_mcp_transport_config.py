import pytest
from mcp.server.transport_security import TransportSecurityMiddleware
from starlette.requests import Request

from app.services.mcp_transport_config import mcp_transport_config


def _request(host: str, origin: str) -> Request:
    return Request({
        "type": "http", "method": "POST", "path": "/mcp",
        "headers": [(b"host", host.encode()), (b"origin", origin.encode()),
                    (b"content-type", b"application/json")],
    })


@pytest.mark.asyncio
async def test_configured_public_origin_preserves_host_and_origin_guards():
    origin, settings = mcp_transport_config(port=8000, public_origin="http://localhost:8090")
    guard = TransportSecurityMiddleware(settings)
    assert await guard.validate_request(_request("localhost:8090", origin), is_post=True) is None
    foreign_host = await guard.validate_request(_request("attacker.example", origin), is_post=True)
    assert foreign_host.status_code == 421
    foreign_origin = await guard.validate_request(
        _request("localhost:8090", "https://attacker.example"), is_post=True,
    )
    assert foreign_origin.status_code == 403


@pytest.mark.parametrize("origin", [
    "https://user:secret@example.com", "https://example.com/path", "https://*.example.com",
    "ftp://example.com", "http://localhost:invalid",
])
def test_invalid_configured_origin_fails_closed(origin):
    with pytest.raises(ValueError, match="mcp_public_origin_invalid"):
        mcp_transport_config(port=8000, public_origin=origin)


def test_local_default_has_no_wildcards():
    origin, settings = mcp_transport_config(port=8000, public_origin=None)
    assert origin == "http://localhost:8000"
    assert all("*" not in host for host in settings.allowed_hosts)
