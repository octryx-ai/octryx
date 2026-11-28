"""Native MCP metadata and DNS-rebinding guards share one configured public origin."""

from urllib.parse import urlsplit

from mcp.server.fastmcp.server import TransportSecuritySettings


def mcp_transport_config(*, port: int, public_origin: str | None) -> tuple[str, TransportSecuritySettings]:
    if not public_origin:
        origin = f"http://localhost:{port}"
        return origin, TransportSecuritySettings(
            allowed_hosts=["localhost", f"localhost:{port}", "127.0.0.1", f"127.0.0.1:{port}", "test"],
            allowed_origins=[origin, f"http://127.0.0.1:{port}"],
        )
    parts = urlsplit(public_origin.strip())
    try:
        configured_port = parts.port
    except ValueError as exc:
        raise ValueError("mcp_public_origin_invalid") from exc
    if (parts.scheme not in {"http", "https"} or not parts.hostname or parts.username is not None
            or parts.password is not None or parts.path not in {"", "/"} or parts.query or parts.fragment
            or "*" in parts.netloc):
        raise ValueError("mcp_public_origin_invalid")
    host = parts.hostname if ":" not in parts.hostname else f"[{parts.hostname}]"
    authority = f"{host}:{configured_port}" if configured_port else host
    origin = f"{parts.scheme}://{authority}"
    return origin, TransportSecuritySettings(allowed_hosts=[authority], allowed_origins=[origin])
