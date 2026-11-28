"""The Cedar principal of the request in progress."""

from __future__ import annotations

import hashlib
import json
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from contextvars import ContextVar
from typing import Any

from .engine import EntityRef

Principal = tuple[EntityRef, list[Mapping[str, Any]]]

_CURRENT: ContextVar[Principal | None] = ContextVar("policy_engine_principal", default=None)


def current_principal() -> Principal | None:
    return _CURRENT.get()


def principal_memo_key(principal: Principal | None = None) -> str | None:
    chosen = principal if principal is not None else current_principal()
    if chosen is None:
        return None
    canonical = json.dumps([chosen[0].label(), list(chosen[1])], sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:24]


async def load_request_principal(
    user_id: str | None, *, session_id: str | None = None, metadata: Mapping[str, Any] | None = None
) -> Principal | None:
    from .principals import load_principal_isolated, load_session_metadata_isolated
    from .runtime import MODE_OFF, current_runtime

    if not user_id or current_runtime().mode == MODE_OFF:
        return None
    if session_id and metadata is None:
        metadata = await load_session_metadata_isolated(session_id)
    return await load_principal_isolated(str(user_id), session_id=session_id, metadata=metadata)


SEAT_PROFILE = "seat"


async def load_seat_principal(user_id: str | None, *, session_id: str, client: str) -> Principal | None:
    return await load_request_principal(user_id, session_id=session_id,
                                        metadata={"profile": SEAT_PROFILE, "client": client})


@asynccontextmanager
async def policy_principal_scope(
    user_id: str | None, *, session_id: str | None = None, metadata: Mapping[str, Any] | None = None
) -> AsyncIterator[Principal | None]:
    principal = await load_request_principal(user_id, session_id=session_id, metadata=metadata)
    token = _CURRENT.set(principal)
    try:
        yield principal
    finally:
        try:
            _CURRENT.reset(token)
        except ValueError:  # closed from another context (an abandoned generator): unbind there instead
            _CURRENT.set(None)


__all__ = [
    "Principal",
    "current_principal",
    "load_request_principal",
    "load_seat_principal",
    "policy_principal_scope",
    "principal_memo_key",
]
