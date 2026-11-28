"""Which physical Confluence a call goes to."""

from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit

EXPECTED_INSTANCE_PARAM = "expected_instance"
EXPECTED_CONNECTION_PARAM = "expected_connection"
DEFAULT_CONNECTION_ID = "default"
REASON_INSTANCE_MISMATCH = "instance_mismatch"
_DEFAULT_PORTS = {"http": 80, "https": 443}


def confluence_instance(url: object) -> str:
    try:
        parts = urlsplit(str(url or "").strip())
        port = parts.port
    except ValueError:
        return ""
    scheme = parts.scheme.lower()
    host = (parts.hostname or "").lower()
    if scheme not in _DEFAULT_PORTS or not host:
        return ""
    netloc = host if port in (None, _DEFAULT_PORTS[scheme]) else f"{host}:{port}"
    return f"{scheme}://{netloc}{parts.path.rstrip('/')}"


def instance_refusal(params: dict[str, Any], confluence_url: str) -> dict[str, Any] | None:
    expected = str(params.get(EXPECTED_INSTANCE_PARAM) or "").strip()
    if not expected:
        return None
    current = confluence_instance(confluence_url)
    if current and current == expected:
        return None
    return {"error": f"{REASON_INSTANCE_MISMATCH}: this connection now serves {current or 'no valid Confluence'}, "
                     f"not the confirmed {expected}", "status_code": 409, "instance_mismatch": True,
            "instance": current}



def connection_refusal(params: dict[str, Any], context: Any) -> dict[str, Any] | None:
    expected = str(params.get(EXPECTED_CONNECTION_PARAM) or "").strip()
    if not expected:
        return None
    actual = str(getattr(context, "connection_id", None) or DEFAULT_CONNECTION_ID)
    if actual == expected:
        return None
    return {"error": f"connection_mismatch: this call is served by connection {actual}, not the confirmed {expected}",
            "status_code": 409, "connection_mismatch": True, "connection_id": actual}


def url_on_instance(url: object, instance: str) -> bool:
    if not instance:
        return False
    try:
        parts = urlsplit(str(url or "").strip())
    except ValueError:
        return False
    base = confluence_instance(parts._replace(query="", fragment="").geturl())
    return base == instance or base.startswith(instance + "/")


__all__ = ["DEFAULT_CONNECTION_ID", "EXPECTED_CONNECTION_PARAM", "EXPECTED_INSTANCE_PARAM", "REASON_INSTANCE_MISMATCH",
           "confluence_instance", "connection_refusal", "instance_refusal", "url_on_instance"]
