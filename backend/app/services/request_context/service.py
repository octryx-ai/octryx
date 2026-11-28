from __future__ import annotations

import re
from contextvars import ContextVar, Token
from datetime import datetime
from uuid import uuid4

from ...time_utils import utc_now

_REQUEST_ID: ContextVar[str | None] = ContextVar("request_id", default=None)
# When the current request id was bound (a run's start). Kept with its id, so a stale value
# from an earlier request in the same context is never returned for a later one.
_REQUEST_STARTED: ContextVar[tuple[str, datetime] | None] = ContextVar("request_started", default=None)

# A caller may supply the request id (``X-Request-ID``) and it is echoed into headers and error bodies, so it stays
# a short token of the shape ``generate_request_id`` produces.
_SAFE_REQUEST_ID_RE = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")


def generate_request_id() -> str:
    return str(uuid4())


def safe_request_id(value: object) -> str | None:
    """*value* when it is a usable request id, else ``None``."""
    candidate = str(value or "").strip()
    return candidate if _SAFE_REQUEST_ID_RE.match(candidate) else None


def set_current_request_id(request_id: str) -> Token:
    _REQUEST_STARTED.set((request_id, utc_now()))
    return _REQUEST_ID.set(request_id)


def get_request_started_at(request_id: str | None) -> datetime | None:
    """When *request_id* was bound in this context, or ``None`` when it is not the current one."""
    started = _REQUEST_STARTED.get()
    return started[1] if started and request_id and started[0] == request_id else None


def get_current_request_id() -> str | None:
    return _REQUEST_ID.get()


def reset_current_request_id(token: Token) -> None:
    _REQUEST_ID.reset(token)
