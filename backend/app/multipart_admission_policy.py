"""Byte budget for multipart requests, decided before anything parses them.

One module owns the numbers and the decision; ``middleware.security.multipart_admission``
owns the ASGI mechanics that apply them. The split keeps this file free of every
application import, which is what lets ``config`` validate the configured ceiling
with the same code the boundary later enforces.

What the boundary decides, in order:

1. A request that does not declare a ``multipart/*`` content type is none of this
   module's business and is passed through untouched.
2. The effective limit is ``min(global ceiling, route ceiling)``. The global
   ceiling is configuration (``Settings.max_multipart_request_bytes``); a route
   ceiling is an explicit entry in ``ROUTE_REQUEST_LIMITS``, never a guess derived
   from the path. ``min`` is deliberate: lowering the global ceiling must lower
   every route with it, so one setting is always an upper bound for the process.
3. The framing itself must be unambiguous. Exactly zero or one ``Content-Length``
   header is admissible, and a single one must be a plain non-empty run of ASCII
   digits. Anything else — empty, signed, non-numeric, a comma-joined list, or a
   second occurrence of the header, identical or not — is malformed framing and is
   refused before the parser. Collapsing duplicates or picking one of several
   candidate lengths would make this boundary count against a length the next hop
   may not agree with, which is exactly the ambiguity a smuggled request needs.
4. A ``Content-Length`` that already exceeds the limit rejects the request without
   reading a single body byte.
5. Everything else — no ``Content-Length``, a dishonest small one, chunked
   transfer — is bounded while streaming by counting raw ASGI ``http.request``
   bytes. A header check alone would be trivially bypassable.

Limits are expressed as *raw request bytes*, not payload bytes: the number the
transport sees includes the multipart envelope (boundary lines, part headers, the
client-supplied file name, the text form fields). Each route ceiling is therefore
its documented payload limit plus ``MULTIPART_ENVELOPE_ALLOWANCE_BYTES``, so a
payload that the route accepts can never be rejected by the boundary for its
envelope alone.

Deliberate boundaries of this contract:

- The route table names raw payload limits as literals instead of importing them
  from the owning services. An ingress policy that imported domain services would
  invert the dependency direction for no gain; ``tests/test_multipart_admission.py``
  pins each literal against the service constant it mirrors, so drift fails a test
  instead of silently clamping a route.
- A path that matches no entry gets the global ceiling only. That is the correct
  direction for an unknown route: bounded, and never *more* permissive than the
  process-wide ceiling.
- This boundary bounds resource use, not authorization. An unauthenticated caller
  may still spend up to the effective limit of one route's budget before
  authentication runs, because the parser runs before a route's dependencies; what
  it may no longer do is spend an unbounded amount.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

# --- Byte budgets -----------------------------------------------------------

# Room for the multipart envelope around an accepted payload: boundary lines,
# per-part headers, the client-supplied file name, and the small text form fields
# the upload routes declare. Generous on purpose — it must never be the reason a
# payload-sized upload is refused — and still negligible next to every limit.
MULTIPART_ENVELOPE_ALLOWANCE_BYTES = 64 * 1024

# The largest payload any current upload route accepts: office template and
# corporate identity packages (``services.office.storage.MAX_UPLOAD_BYTES`` and
# ``services.corp_identity.uploads.MAX_UPLOAD_BYTES``, both 512 MiB). The default
# global ceiling is derived from it so installing this boundary cannot refuse an
# upload the product accepts today. Deployments that do not need those surfaces
# should configure a much lower ceiling.
LARGEST_ROUTE_PAYLOAD_BYTES = 512 * 1024 * 1024

DEFAULT_MULTIPART_REQUEST_BYTES = LARGEST_ROUTE_PAYLOAD_BYTES + MULTIPART_ENVELOPE_ALLOWANCE_BYTES

# A configured ceiling below one envelope allowance cannot carry any multipart
# request at all, so it is a typo rather than a hardening choice.
MIN_MULTIPART_REQUEST_BYTES = MULTIPART_ENVELOPE_ALLOWANCE_BYTES

# Above this, a configured ceiling stops being a ceiling: it is more than any
# route accepts and would let one request occupy an amount of memory, socket time
# and temporary storage no deployment agreed to. Rejected as effectively
# unbounded instead of being silently clamped.
MAX_MULTIPART_REQUEST_BYTES = 2 * LARGEST_ROUTE_PAYLOAD_BYTES

# Payload limit of the canonical Workspace Knowledge Evidence upload, mirroring
# ``services.knowledge.ingestion.text_ingest.MAX_UPLOAD_BYTES`` (32 MiB since PDF and
# Office documents go to the Docling sandbox).
KNOWLEDGE_EVIDENCE_PAYLOAD_BYTES = 32 * 1024 * 1024
KNOWLEDGE_EVIDENCE_REQUEST_BYTES = KNOWLEDGE_EVIDENCE_PAYLOAD_BYTES + MULTIPART_ENVELOPE_ALLOWANCE_BYTES

KNOWLEDGE_EVIDENCE_UPLOAD_ROUTE = "/api/v1/workspaces/{workspace_id}/knowledge/sources"

# Explicit, closed registration of route ceilings below the global one. Templates
# are matched segment by segment (``{name}`` matches exactly one non-empty
# segment), which is the same shape Starlette routes with, so a path that does not
# match an entry here cannot reach the route the entry protects either.
ROUTE_REQUEST_LIMITS: tuple[tuple[str, int], ...] = (
    (KNOWLEDGE_EVIDENCE_UPLOAD_ROUTE, KNOWLEDGE_EVIDENCE_REQUEST_BYTES),
)

# Route policy identifier used in logs when no route entry matched. The client's
# own path is never logged: it carries workspace and resource identifiers.
GLOBAL_ROUTE_POLICY = "multipart:global"

MULTIPART_CONTENT_TYPE_PREFIX = "multipart/"

# --- Request framing --------------------------------------------------------

# Outcome of reading the declared body length. ``ABSENT`` means "unknown length"
# (chunked or streamed) and must be bounded by counting bytes; ``MALFORMED`` is a
# refusal, never a fallback to counting, because a request whose framing two hops
# could read differently must not be forwarded at all.
CONTENT_LENGTH_ABSENT = "absent"
CONTENT_LENGTH_DECLARED = "declared"
CONTENT_LENGTH_MALFORMED = "malformed"

# ``str.isdigit`` is true for characters ``int()`` refuses (superscripts) and for
# non-ASCII decimal digits no HTTP field value may carry, so the admissible
# charset is spelled out instead.
_ASCII_DIGITS = frozenset("0123456789")


class MultipartAdmissionConfigError(ValueError):
    """Rejection of a configured multipart ceiling.

    Carries a fixed, input-free message so startup can surface it verbatim
    without echoing the configured value.
    """


def validate_multipart_request_bytes(value: object) -> int:
    """Return the configured ceiling, or fail closed.

    Rejects non-integers, zero and negative values (no "unlimited" sentinel
    exists), values too small to carry any multipart envelope, and values so large
    that the ceiling is effectively absent. Nothing is clamped: an operator who
    mistyped the ceiling must see it at startup rather than inherit a limit
    nobody chose.
    """
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
    """True when the declared content type asks for multipart form parsing."""
    return str(content_type or "").strip().lower().startswith(MULTIPART_CONTENT_TYPE_PREFIX)


def _header_values(headers: Mapping[str, str] | Any, name: str) -> list[str]:
    """Every occurrence of one header, in wire order."""
    getlist = getattr(headers, "getlist", None)
    if callable(getlist):
        return [str(value) for value in getlist(name)]
    if isinstance(headers, Mapping):
        value = headers.get(name)
        return [] if value is None else [str(value)]
    raise TypeError("headers must be a starlette Headers or a Mapping")


def declared_content_length(headers: Mapping[str, str] | Any) -> tuple[str, int | None]:
    """The declared body length as an explicit framing state.

    Returns one of:

    - ``(CONTENT_LENGTH_ABSENT, None)`` — nothing was declared. Unknown length,
      not empty: the caller must bound the request by counting streamed bytes.
    - ``(CONTENT_LENGTH_DECLARED, value)`` — exactly one well-formed header.
    - ``(CONTENT_LENGTH_MALFORMED, None)`` — the request's framing is ambiguous
      and the caller must refuse it without reading or forwarding a byte.

    Malformed covers an empty, signed, non-numeric or comma-joined value and any
    second occurrence of the header. Duplicates are refused even when the values
    agree: de-duplicating request framing belongs to the hop that owns the wire,
    and an admission boundary that repairs it would be counting bytes against a
    length some other hop may resolve differently.
    """
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
    """The path a router matches on: the request path without the ASGI root path.

    Mirrors Starlette's own ``get_route_path``. Without it, an application served
    under a root path (an ingress that mounts the API under a prefix) would present
    prefixed paths here, no route entry would match, and a route with its own lower
    ceiling would silently fall back to the global one.
    """
    root = str(root_path or "").rstrip("/")
    candidate = str(path or "")
    if root and candidate.startswith(root):
        return candidate[len(root) :] or "/"
    return candidate


def _matches_route_template(template: str, path: str) -> bool:
    """Segment-wise match of a route template against a decoded request path."""
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
    """The registered route ceiling for a path, with its policy identifier."""
    for template, limit in ROUTE_REQUEST_LIMITS:
        if _matches_route_template(template, str(path or "")):
            return template, limit
    return None


def resolve_request_limit(path: str, *, global_limit: int) -> tuple[str, int]:
    """Effective ceiling for one request path, with the policy identifier to log.

    The route ceiling never raises the global one: ``min`` keeps the configured
    setting an upper bound for the whole process.
    """
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
