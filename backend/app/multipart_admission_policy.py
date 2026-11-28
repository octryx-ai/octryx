"""Byte budget for multipart requests, decided before anything parses them."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

# Generous on purpose: the envelope must never be the reason a payload-sized upload is refused.
MULTIPART_ENVELOPE_ALLOWANCE_BYTES = 64 * 1024

# The largest current route payload (office and corporate identity uploads), so the default ceiling refuses
# nothing the product accepts today; deployments without those surfaces should configure a much lower one.
LARGEST_ROUTE_PAYLOAD_BYTES = 512 * 1024 * 1024

DEFAULT_MULTIPART_REQUEST_BYTES = LARGEST_ROUTE_PAYLOAD_BYTES + MULTIPART_ENVELOPE_ALLOWANCE_BYTES

# A ceiling below one envelope cannot carry any multipart request, so it is a typo, not hardening.
MIN_MULTIPART_REQUEST_BYTES = MULTIPART_ENVELOPE_ALLOWANCE_BYTES

# Above this one request could occupy memory, socket time and storage no deployment agreed to;
# rejected as effectively unbounded instead of being silently clamped.
MAX_MULTIPART_REQUEST_BYTES = 2 * LARGEST_ROUTE_PAYLOAD_BYTES

# Mirrors ``services.knowledge.ingestion.text_ingest.MAX_UPLOAD_BYTES``.
KNOWLEDGE_EVIDENCE_PAYLOAD_BYTES = 32 * 1024 * 1024
KNOWLEDGE_EVIDENCE_REQUEST_BYTES = KNOWLEDGE_EVIDENCE_PAYLOAD_BYTES + MULTIPART_ENVELOPE_ALLOWANCE_BYTES

KNOWLEDGE_EVIDENCE_UPLOAD_ROUTE = "/api/v1/workspaces/{workspace_id}/knowledge/sources"

# Templates match segment by segment, the shape Starlette routes with, so a path that matches no
# entry cannot reach the route the entry protects either.
ROUTE_REQUEST_LIMITS: tuple[tuple[str, int], ...] = (
    (KNOWLEDGE_EVIDENCE_UPLOAD_ROUTE, KNOWLEDGE_EVIDENCE_REQUEST_BYTES),
)

# Per form, wherever an upload is parsed (``http_multipart_route.BoundedFormRoute``): Starlette's own defaults are
# 1000 files and 1000 fields.
MAX_FORM_FILES = 100
MAX_FORM_FIELDS = 100
MAX_FORM_FIELD_BYTES = 1024 * 1024

# Logged when no route matched; the client's path is never logged as it carries resource identifiers.
GLOBAL_ROUTE_POLICY = "multipart:global"

MULTIPART_CONTENT_TYPE_PREFIX = "multipart/"

# ``ABSENT`` (chunked or streamed) is bounded by counting bytes; ``MALFORMED`` is a refusal, never a
# fallback, because a request whose framing two hops could read differently must not be forwarded.
CONTENT_LENGTH_ABSENT = "absent"
CONTENT_LENGTH_DECLARED = "declared"
CONTENT_LENGTH_MALFORMED = "malformed"

# ``str.isdigit`` accepts superscripts and non-ASCII digits, so the HTTP charset is spelled out.
_ASCII_DIGITS = frozenset("0123456789")


class MultipartAdmissionConfigError(ValueError):
    pass


def validate_multipart_request_bytes(value: object) -> int:
    if type(value) is not int:
        raise MultipartAdmissionConfigError(
            "max_multipart_request_bytes must be an integer number of bytes"
        )
    if value < MIN_MULTIPART_REQUEST_BYTES:
        raise MultipartAdmissionConfigError(
            "max_multipart_request_bytes must be at least "
            f"{MIN_MULTIPART_REQUEST_BYTES} bytes; it bounds whole multipart requests, "
            "envelope included"
        )
    if value > MAX_MULTIPART_REQUEST_BYTES:
        raise MultipartAdmissionConfigError(
            "max_multipart_request_bytes must not exceed "
            f"{MAX_MULTIPART_REQUEST_BYTES} bytes; a higher value is not a ceiling"
        )
    return value


def is_multipart_content_type(content_type: str | None) -> bool:
    return str(content_type or "").strip().lower().startswith(MULTIPART_CONTENT_TYPE_PREFIX)


def _header_values(headers: Mapping[str, str] | Any, name: str) -> list[str]:
    getlist = getattr(headers, "getlist", None)
    if callable(getlist):
        return [str(value) for value in getlist(name)]
    if isinstance(headers, Mapping):
        value = headers.get(name)
        return [] if value is None else [str(value)]
    raise TypeError("headers must be a starlette Headers or a Mapping")


def declared_content_length(headers: Mapping[str, str] | Any) -> tuple[str, int | None]:
    raw_values = _header_values(headers, "content-length")
    if not raw_values:
        return CONTENT_LENGTH_ABSENT, None
    if len(raw_values) > 1:
        return CONTENT_LENGTH_MALFORMED, None
    candidate = raw_values[0].strip()
    if not candidate or set(candidate) - _ASCII_DIGITS:
        return CONTENT_LENGTH_MALFORMED, None
    return CONTENT_LENGTH_DECLARED, int(candidate)


def route_path(path: str | None, root_path: str | None = "") -> str:
    root = str(root_path or "").rstrip("/")
    candidate = str(path or "")
    if root and candidate.startswith(root):
        return candidate[len(root) :] or "/"
    return candidate


def _matches_route_template(template: str, path: str) -> bool:
    template_segments = template.strip("/").split("/")
    path_segments = path.strip("/").split("/")
    if len(template_segments) != len(path_segments):
        return False
    for expected, actual in zip(template_segments, path_segments, strict=True):
        if expected.startswith("{") and expected.endswith("}"):
            if not actual:
                return False
            continue
        if expected != actual:
            return False
    return True


def route_request_limit(path: str) -> tuple[str, int] | None:
    for template, limit in ROUTE_REQUEST_LIMITS:
        if _matches_route_template(template, str(path or "")):
            return template, limit
    return None


def resolve_request_limit(path: str, *, global_limit: int) -> tuple[str, int]:
    matched = route_request_limit(path)
    if matched is None:
        return GLOBAL_ROUTE_POLICY, global_limit
    template, limit = matched
    return template, min(limit, global_limit)


__all__ = [
    "CONTENT_LENGTH_ABSENT",
    "CONTENT_LENGTH_DECLARED",
    "CONTENT_LENGTH_MALFORMED",
    "DEFAULT_MULTIPART_REQUEST_BYTES",
    "GLOBAL_ROUTE_POLICY",
    "KNOWLEDGE_EVIDENCE_PAYLOAD_BYTES",
    "KNOWLEDGE_EVIDENCE_REQUEST_BYTES",
    "KNOWLEDGE_EVIDENCE_UPLOAD_ROUTE",
    "LARGEST_ROUTE_PAYLOAD_BYTES",
    "MAX_FORM_FIELDS",
    "MAX_FORM_FIELD_BYTES",
    "MAX_FORM_FILES",
    "MAX_MULTIPART_REQUEST_BYTES",
    "MIN_MULTIPART_REQUEST_BYTES",
    "MULTIPART_ENVELOPE_ALLOWANCE_BYTES",
    "ROUTE_REQUEST_LIMITS",
    "MultipartAdmissionConfigError",
    "declared_content_length",
    "is_multipart_content_type",
    "resolve_request_limit",
    "route_path",
    "route_request_limit",
    "validate_multipart_request_bytes",
]
