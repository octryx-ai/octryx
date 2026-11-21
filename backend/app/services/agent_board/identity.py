"""The agent identity behind a claim or a board post.

- **gateway_session:** the call carries an ``octryx-claude`` session (``X-Octryx-Session``; the
  launcher's MCP ``headersHelper`` sends it). The session must be one the caller registered
  (``agent_presence``), otherwise the call is refused (``agent_session_invalid``), so nobody can act as
  another user's agent. Its reference is the presence hash of the session key.
- **mcp_session:** any other MCP client: the OAuth grant behind its auto-session (``mcp_auto_session``).
  The grant, not the per-day auto-session row, is the stable identity.
- **chat_session:** a platform chat session (chat-client parity: the chat can do what the
  client can). The chat runs the client's claim, board and handoff handlers
  as its own agent: the reference is the hash of the server-side session id, so a chat can neither act as a client
  session nor as another chat. The owner of the session is the user.

Only the 24-hex hash is stored and shown; a raw session key or grant id never leaves the server. A human is
never an agent identity.
"""

from __future__ import annotations

import hashlib
import uuid
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import AgentPresence
from ..agent_gateway.contract import HEADER_SESSION
from ..agent_gateway.presence import session_key_hash
from .claim_values import KIND_CHAT_SESSION, KIND_GATEWAY_SESSION, KIND_MCP_SESSION

REASON_AGENT_SESSION_INVALID = "agent_session_invalid"


@dataclass(frozen=True, slots=True)
class AgentIdentity:
    kind: str
    ref_hash: str
    user_id: str
    session_key: str = ""  # gateway sessions only; never returned or stored
    project_id: str = ""  # the gateway session's Workspace; empty for MCP grants

    def holder(self) -> dict[str, str]:
        return {"kind": self.kind, "ref_hash": self.ref_hash, "user_id": self.user_id}


def mcp_identity_hash(grant_id: str | None, user_id: str) -> str:
    seed = f"mcp:{grant_id}" if grant_id else f"mcp-user:{user_id}"
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()[:24]


def chat_session_identity(*, user_id: str, session_id: str, project_ids: Any = ()) -> AgentIdentity:
    """The agent identity of a platform chat session; its Workspace is the session's only one, else none."""
    if not str(session_id or "").strip():
        raise HTTPException(status_code=403, detail={"code": REASON_AGENT_SESSION_INVALID})
    ref_hash = hashlib.sha256(f"chat:{session_id}".encode()).hexdigest()[:24]
    projects = sorted({str(project).strip() for project in project_ids or () if str(project).strip()})
    return AgentIdentity(KIND_CHAT_SESSION, ref_hash, user_id, project_id=projects[0] if len(projects) == 1 else "")


IdentityRun = Callable[[Any, AgentIdentity, Any, dict[str, Any]], Awaitable[dict[str, Any]]]


def identity_handler(run: IdentityRun, *, headers: Mapping[str, str] | None = None,
                     identity: AgentIdentity | None = None) -> Any:
    """A secure-work handler running ``run`` as the call's agent: ``identity`` when given (a chat), else the one the
    MCP call's ``headers`` name. A fixed identity must belong to the calling user."""

    async def handler(db: AsyncSession, *, user: Any, scope: Any, arguments: dict[str, Any]) -> dict[str, Any]:
        if identity is not None:
            if identity.user_id != user.id:
                raise HTTPException(status_code=403, detail={"code": REASON_AGENT_SESSION_INVALID})
            who = identity
        else:
            who = await resolve_agent_identity(db, user_id=user.id, grant_id=scope.grant_id, headers=headers or {})
        return await run(db, who, scope, arguments)

    return handler


async def resolve_agent_identity(
    db: AsyncSession, *, user_id: str, grant_id: str | None, headers: Mapping[str, str]
) -> AgentIdentity:
    raw = str(headers.get(HEADER_SESSION) or "").strip()
    if raw:
        try:
            session_key = str(uuid.UUID(raw))
        except ValueError:
            raise HTTPException(status_code=403, detail={"code": REASON_AGENT_SESSION_INVALID}) from None
        owned = (
            await db.execute(
                select(AgentPresence.project_id).where(
                    AgentPresence.session_key == session_key, AgentPresence.user_id == user_id
                )
            )
        ).first()
        if owned is None:
            raise HTTPException(status_code=403, detail={"code": REASON_AGENT_SESSION_INVALID})
        return AgentIdentity(KIND_GATEWAY_SESSION, session_key_hash(session_key), user_id, session_key, owned[0])
    return AgentIdentity(KIND_MCP_SESSION, mcp_identity_hash(grant_id, user_id), user_id)


def request_headers(ctx: object) -> Mapping[str, str]:
    """The HTTP headers of an MCP tool call (empty when there is no HTTP request)."""
    request = getattr(getattr(ctx, "request_context", None), "request", None)
    headers = getattr(request, "headers", None)
    return headers if headers is not None else {}


__all__ = [
    "REASON_AGENT_SESSION_INVALID",
    "AgentIdentity",
    "chat_session_identity",
    "identity_handler",
    "mcp_identity_hash",
    "request_headers",
    "resolve_agent_identity",
]
