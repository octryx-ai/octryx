"""The Cedar principal of the request in progress.

Without an explicit principal an enforcement point evaluates as ``User::"unknown"``, and who-conditions (users,
roles, groups, session profile/client, except platform admins) do not bite. This module carries the principal to
every enforcement point explicitly:

- :func:`policy_principal_scope` is entered once where a request's user and session are known — an agent run
  (``agent/engine/_engine_run_scope``), an inbound model-gateway call, an MCP listing or tool call — and loads the
  principal (platform roles, identity groups, the session's profile and client) in its own database session;
- the tool admission and the remote-model points read :func:`current_principal` when they build their query;
- a model admission captures it when it is built (``ProjectModelAdmission.principal``), so its later re-checks at
  the driver decide for the same principal;
- the seat check receives its principal as an argument from the gateway identity.

Outside any scope (a system job, Knowledge indexing) the principal stays ``User::"unknown"``: honest, not guessed.
Loading never raises: a principal without roles or groups only narrows less, it never grants.
"""

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
    """A stable key of the principal and its parents/attributes, for memoised listing decisions."""
    chosen = principal if principal is not None else current_principal()
    if chosen is None:
        return None
    canonical = json.dumps([chosen[0].label(), list(chosen[1])], sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:24]


async def load_request_principal(
    user_id: str | None, *, session_id: str | None = None, metadata: Mapping[str, Any] | None = None
) -> Principal | None:
    """The principal of ``user_id`` (and its AgentSession when ``session_id`` is given); ``None`` without a user."""
    from .principals import load_principal_isolated, load_session_metadata_isolated
    from .runtime import MODE_OFF, current_runtime

    if not user_id or current_runtime().mode == MODE_OFF:
        return None
    if session_id and metadata is None:
        metadata = await load_session_metadata_isolated(session_id)
    return await load_principal_isolated(str(user_id), session_id=session_id, metadata=metadata)


SEAT_PROFILE = "seat"


async def load_seat_principal(user_id: str | None, *, session_id: str, client: str) -> Principal | None:
    """The principal of a seat request: the user, and the session asking for the ``seat`` profile."""
    return await load_request_principal(user_id, session_id=session_id,
                                        metadata={"profile": SEAT_PROFILE, "client": client})


@asynccontextmanager
async def policy_principal_scope(
    user_id: str | None, *, session_id: str | None = None, metadata: Mapping[str, Any] | None = None
) -> AsyncIterator[Principal | None]:
    """Bind the request's principal for the enforcement points inside the block (restored on exit)."""
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
