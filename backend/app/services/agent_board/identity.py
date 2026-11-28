"""The agent identity behind a claim or a board post."""

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
    if not str(session_id or "").strip():
        raise HTTPException(status_code=403, detail={"code": REASON_AGENT_SESSION_INVALID})
    ref_hash = hashlib.sha256(f"chat:{session_id}".encode()).hexdigest()[:24]
    projects = sorted({str(project).strip() for project in project_ids or () if str(project).strip()})
    return AgentIdentity(KIND_CHAT_SESSION, ref_hash, user_id, project_id=projects[0] if len(projects) == 1 else "")


IdentityRun = Callable[[Any, AgentIdentity, Any, dict[str, Any]], Awaitable[dict[str, Any]]]


def identity_handler(run: IdentityRun, *, headers: Mapping[str, str] | None = None,
                     identity: AgentIdentity | None = None) -> Any:
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
