"""Names, keys and the read rule of the custom REST connector.

Tool names are ``rest__<definition key>__<operation name>``. Both parts are lower snake case and short enough that
the whole name stays within the 64 characters the model APIs accept for a function name (6 + 24 + 2 + 32).
"""

from __future__ import annotations

import re
from urllib.parse import urlsplit

from fastapi import HTTPException

REST_TOOL_PREFIX = "rest__"
KEY_RE = re.compile(r"^[a-z][a-z0-9_]{0,23}$")
OP_KEY_RE = re.compile(r"^[a-z][a-z0-9_]{0,31}$")
READ_METHODS = frozenset({"GET", "HEAD"})
METHODS = ("GET", "HEAD", "POST", "PUT", "PATCH", "DELETE")
AUTH_SCHEMES = ("none", "api_key_header", "api_key_query", "bearer", "basic", "oauth2_client_credentials")
#: The run class a write operation needs. ``deliver`` (an external write) unless its admin explicitly says ``change``.
WRITE_CAPABILITIES = ("deliver", "change")
DEFAULT_WRITE_CAPABILITY = "deliver"
#: Methods a retry may repeat only when the admin marked the operation idempotent (never POST/PATCH).
IDEMPOTENT_CANDIDATE_METHODS = frozenset({"PUT", "DELETE"})


def secret_scope(connection_id: str) -> str:
    """The secret-store ``tool_name`` of one connection: a ref copied to another connection never resolves."""
    return f"rest_api_connection:{connection_id}"


def tool_name_for(definition_key: str, op_name: str) -> str:
    return f"{REST_TOOL_PREFIX}{definition_key}__{op_name}"


def split_tool_name(tool_name: str) -> tuple[str, str] | None:
    """``(definition key, operation name)`` of a ``rest__`` tool name, else ``None``."""
    name = str(tool_name or "")
    if not name.startswith(REST_TOOL_PREFIX):
        return None
    definition_key, separator, op_name = name[len(REST_TOOL_PREFIX):].partition("__")
    if not separator or not KEY_RE.fullmatch(definition_key) or not OP_KEY_RE.fullmatch(op_name):
        return None
    return definition_key, op_name


def is_read_operation(method: str, read_only: bool) -> bool:
    """GET/HEAD, and a POST an admin marked read-only (a search endpoint); everything else writes."""
    normalized = str(method or "").upper()
    return normalized in READ_METHODS or (normalized == "POST" and bool(read_only))


def write_capability(operation: object) -> str | None:
    """The run class a write operation needs (``deliver`` unless the admin set ``change``); ``None`` for a read."""
    if is_read_operation(getattr(operation, "method", ""), bool(getattr(operation, "read_only", False))):
        return None
    declared = str(getattr(operation, "capability", None) or "").strip()
    return declared if declared in WRITE_CAPABILITIES else DEFAULT_WRITE_CAPABILITY


def retry_allowed(operation: object) -> bool:
    """A failed call may be sent again only when repeating it cannot do the write twice.

    GET/HEAD read; PUT/DELETE repeat safely only if the admin says this API implements them idempotently; a POST or
    PATCH is never repeated (a 503 after the server already created the record would create it twice)."""
    method = str(getattr(operation, "method", "") or "").upper()
    if method in READ_METHODS:
        return True
    return method in IDEMPOTENT_CANDIDATE_METHODS and bool(getattr(operation, "idempotent", False))


def validate_key(raw: object) -> str:
    key = str(raw or "").strip()
    if not KEY_RE.fullmatch(key):
        raise HTTPException(
            status_code=400, detail="key: 1-24 lower-case letters, digits or '_', starting with a letter"
        )
    return key


def validate_op_name(raw: object, *, field: str = "op_key") -> str:
    name = str(raw or "").strip()
    if not OP_KEY_RE.fullmatch(name):
        raise HTTPException(
            status_code=400, detail=f"{field}: 1-32 lower-case letters, digits or '_', starting with a letter"
        )
    return name


def http_url_problem(raw: object) -> str | None:
    """Why ``raw`` is not an http(s) URL with a host, else ``None``.

    In the SAP Business Accelerator Hub specs (e.g. Business Partner A2X), ``https://{host}:{port}/sap/opu/...`` with
    empty variable defaults reads as ``https://:/sap/opu/...``; such a server must never be offered as a base URL.
    """
    url = str(raw or "").strip()
    try:
        parts = urlsplit(url)
        parts.port  # noqa: B018 - raises on a port that is not a number
    except ValueError:
        return "is not a URL"
    if parts.scheme not in {"https", "http"}:
        return "must start with http:// or https://"
    if not parts.hostname:
        return "has no host"
    return None


def snake_case(raw: object, *, limit: int = 32) -> str:
    """A model-friendly operation key from an ``operationId`` or ``method + path``."""
    text = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", str(raw or ""))
    text = re.sub(r"[^A-Za-z0-9]+", "_", text).strip("_").lower()
    if not text or not text[0].isalpha():
        text = f"op_{text}".strip("_")
    return text[:limit].rstrip("_") or "op"


__all__ = [
    "AUTH_SCHEMES",
    "KEY_RE",
    "METHODS",
    "OP_KEY_RE",
    "DEFAULT_WRITE_CAPABILITY",
    "IDEMPOTENT_CANDIDATE_METHODS",
    "READ_METHODS",
    "REST_TOOL_PREFIX",
    "WRITE_CAPABILITIES",
    "http_url_problem",
    "is_read_operation",
    "retry_allowed",
    "secret_scope",
    "snake_case",
    "split_tool_name",
    "tool_name_for",
    "validate_key",
    "validate_op_name",
    "write_capability",
]
