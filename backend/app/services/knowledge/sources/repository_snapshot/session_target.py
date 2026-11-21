"""The session's recorded repository binding as a codebase target (resolver step 4).

``session_repository_target`` turns the launcher's binding of one gateway session (``binding.py``)
into the ``session_target`` that ``code/codebase.resolve_codebase`` takes:

- ``None``: there is no session key, no session of this user in this Workspace, or no binding. The
  resolver goes on to its next step;
- :class:`SessionRepositoryTarget`: the bound repository source is indexed at exactly the bound HEAD
  commit, and the resolver reads that source;
- a ``CodebaseRefusal``: the session is bound, but its codebase cannot be answered:
  - ``no_repository_source``: no source exists for the remote, because the snapshot was not allowed;
  - ``repository_sync_in_progress``: the snapshot is still uploading;
  - ``repository_not_synced``: the source is at another commit. A stale index never stands in for
    "this codebase".

The session is looked up by its launcher key. It must belong to the caller and the Workspace,
exactly like the gateway's own session rule (``agent_gateway/sessions``).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .....models import Session
from ...code.codebase import (
    REASON_NO_REPOSITORY_SOURCE,
    REASON_NOT_SYNCED,
    REASON_SYNC_IN_PROGRESS,
    STATE_NEEDS_CONFIGURATION,
    CodebaseRefusal,
)
from ..sync.cursor import SyncCursor
from ..sync.git_config import HEAD_COMMIT
from .binding import repository_connector, session_binding

GATEWAY_SESSION_KEY_METADATA = "gateway_session_key"
EXTERNAL_AGENT_TYPE = "external_agent"


@dataclass(frozen=True, slots=True)
class SessionRepositoryTarget:
    connector_id: str
    connector_key: str
    head_commit: str
    head_dirty: bool
    head_pushed: bool


async def bound_gateway_session(
    db: AsyncSession, *, user_id: str, workspace_id: str, session_key: str | None
) -> Session | None:
    """The caller's gateway session in this Workspace for ``session_key``, or ``None``."""
    try:
        key = str(uuid.UUID(str(session_key or "")))
    except ValueError:
        return None
    session = (
        await db.execute(
            select(Session)
            .where(
                Session.agent_type == EXTERNAL_AGENT_TYPE,
                Session.metadata_[GATEWAY_SESSION_KEY_METADATA].as_string() == key,
            )
            .limit(1)
        )
    ).scalar_one_or_none()
    if session is None or session.user_id != user_id or session.project_id != workspace_id:
        return None
    return session


async def session_repository_target(
    db: AsyncSession, *, user_id: str, workspace_id: str, session_key: str | None
) -> SessionRepositoryTarget | CodebaseRefusal | None:
    session = await bound_gateway_session(db, user_id=user_id, workspace_id=workspace_id, session_key=session_key)
    binding = session_binding(session) if session is not None else None
    if binding is None:
        return None
    connector_key = str(binding.get("connector_key") or "")
    candidate = ({"repository": connector_key, "repository_url": binding.get("remote"), "commit": None},)
    connector = await repository_connector(db, workspace_id, connector_key)
    if connector is None:
        return CodebaseRefusal(STATE_NEEDS_CONFIGURATION, REASON_NO_REPOSITORY_SOURCE, candidate)
    scope = dict(connector.scope or {})
    bound_head = str(binding.get("head_commit") or "")
    if SyncCursor.load(connector.cursor).pass_open:
        return CodebaseRefusal(STATE_NEEDS_CONFIGURATION, REASON_SYNC_IN_PROGRESS, candidate)
    if scope.get(HEAD_COMMIT) != bound_head:
        return CodebaseRefusal(STATE_NEEDS_CONFIGURATION, REASON_NOT_SYNCED, candidate)
    return SessionRepositoryTarget(
        connector_id=connector.id,
        connector_key=connector_key,
        head_commit=bound_head,
        head_dirty=binding.get("head_dirty") is True,
        head_pushed=binding.get("head_pushed") is True,
    )


__all__ = ["SessionRepositoryTarget", "bound_gateway_session", "session_repository_target"]
