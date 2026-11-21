"""Passive record of the S3 wire traffic the product object store produced.

The observer registers botocore event handlers and never changes a request: it
exists so the live smoke can prove *which* S3 operations the real
``KnowledgeObjectStore`` issued, on what addressing style, and with which
headers, instead of trusting the product docstring.

Only non-secret facts are retained. Header *names* are kept, never their values,
with two exceptions, both validated against a narrow shape first: ``If-None-Match`` is kept
after being compared with the single literal the product is allowed to send, and the
``prefix`` query parameter of a listing is kept because it is derived by the product from a
Workspace id and is what proves a list was never bucket-wide. The ``Authorization`` header is
therefore recorded as present without its content ever being read.

Attach it to a ``boto3`` session that only product code uses; the fixture's own
administrative client runs on a separate session so it is never recorded.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# Every operation the immutable ingestion/retrieval store may reach the wire with.
ALLOWED_OPERATIONS = frozenset({"PutObject", "GetObject"})
# And the two the operator-owned maintenance capability may use. The sets are kept
# apart on purpose: a phase asserts against exactly the one its capability owns, so a store
# that ever issued a delete, or a maintenance pass that ever read an object, fails here.
MAINTENANCE_OPERATIONS = frozenset({"ListObjectsV2", "DeleteObject"})

# Narrow shape of a retained prefix: the product derives it from a Workspace id.
_PREFIX_VALUE = re.compile(r"^[a-z0-9][a-z0-9/_-]{0,255}$")


@dataclass(frozen=True, slots=True)
class WireAttempt:
    """One HTTP attempt: shape only, no header value and no body."""

    method: str
    host: str
    path: str
    header_names: frozenset[str]
    if_none_match: str
    list_prefix: str

    @property
    def is_signed(self) -> bool:
        return "authorization" in self.header_names

    def is_path_style_for(self, bucket: str) -> bool:
        """True when the bucket is addressed in the path, not in the host name.

        An object operation addresses ``/<bucket>/<key>``; a bucket-level operation such as
        ``ListObjectsV2`` addresses ``/<bucket>`` with its parameters in the query. Both are
        path-style, and neither may put the bucket into the host name.
        """
        if self.host.startswith(f"{bucket}."):
            return False
        return self.path == f"/{bucket}" or self.path.startswith(f"/{bucket}/")


@dataclass(slots=True)
class WireObserver:
    """Records the product client's API calls and HTTP attempts, in order."""

    operations: list[str] = field(default_factory=list)
    attempts: list[WireAttempt] = field(default_factory=list)

    def attach(self, session: object) -> None:
        """Register on a boto3 session. Safe to call again after a new session."""
        events = session.events  # type: ignore[attr-defined]
        events.register("before-call.s3", self._record_operation)
        events.register("before-send.s3", self._record_attempt)

    def reset(self) -> None:
        self.operations.clear()
        self.attempts.clear()

    def take(self) -> tuple[tuple[str, ...], tuple[WireAttempt, ...]]:
        """Return everything recorded so far and start a fresh window."""
        recorded = (tuple(self.operations), tuple(self.attempts))
        self.reset()
        return recorded

    # botocore handlers. Both must return None: a non-None return value from
    # ``before-send`` would replace the HTTP response and change behavior.
    def _record_operation(self, model: object = None, **_: object) -> None:
        name = getattr(model, "name", "")
        self.operations.append(name if type(name) is str else "")

    def _record_attempt(self, request: object = None, **_: object) -> None:
        method = getattr(request, "method", "")
        url = getattr(request, "url", "")
        headers = getattr(request, "headers", None)
        names = frozenset(
            name.lower() for name in (headers.keys() if headers is not None else ()) if type(name) is str
        )
        precondition = ""
        if headers is not None:
            raw = headers.get("If-None-Match")
            # Only the exact literal the product is allowed to send is retained.
            if raw == "*" or raw == b"*":
                precondition = "*"
            elif raw is not None:
                precondition = "<unexpected>"
        host, path, query = _split(url if type(url) is str else "")
        self.attempts.append(
            WireAttempt(
                method=method if type(method) is str else "",
                host=host,
                path=path,
                header_names=names,
                if_none_match=precondition,
                list_prefix=_prefix(query),
            )
        )


def _split(url: str) -> tuple[str, str, str]:
    """Split ``scheme://host/path?query`` into host, path and query."""
    remainder = url.split("://", 1)[-1]
    host, _, tail = remainder.partition("/")
    path, _, query = f"/{tail}".partition("?")
    return host, path, query


def _prefix(query: str) -> str:
    """The ``prefix`` parameter of a listing, or "" when the request carries none.

    A value outside the narrow derived shape is recorded as ``<unexpected>`` rather than
    retained, so nothing arbitrary from a request can travel into the acceptance output.
    """
    for parameter in query.split("&"):
        name, separator, value = parameter.partition("=")
        if name != "prefix" or not separator:
            continue
        decoded = value.replace("%2F", "/").replace("%2f", "/")
        return decoded if _PREFIX_VALUE.fullmatch(decoded) else "<unexpected>"
    return ""
