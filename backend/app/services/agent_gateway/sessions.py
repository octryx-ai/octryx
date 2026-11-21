"""The platform shadow session behind one ``octryx-claude`` launcher session.

The launcher generates a session key (UUID) and sends it with every model call and
hook call. The first authenticated call creates one ``external_agent`` Session for
that key; every later call — model traffic, tool policy, verification, finalize —
lands on the same row, so the whole client session is one browsable platform
session with its usage, messages and tool calls.

A key is owned by the user and Workspace that created it: the same key presented by
another user or for another Workspace is refused, never re-attached.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import Session
from .contract import (
    EXTERNAL_AGENT_TYPE,
    GATEWAY_CLIENT,
    GATEWAY_EXTERNAL_SOURCE,
    REASON_SESSION_NOT_FOUND,
    REASON_SESSION_OWNER_MISMATCH,
    REASON_SESSION_WORKSPACE_MISMATCH,
    SESSION_KEY_METADATA,
    STATE_DENIED,
    STATE_NEEDS_CONFIGURATION,
)
from .identity import GatewayIdentity, GatewayRefusal


async def _find_by_key(db: AsyncSession, session_key: str) -> Session | None:
    return (
        await db.execute(
            select(Session)
            .where(
                Session.agent_type == EXTERNAL_AGENT_TYPE,
                Session.metadata_[SESSION_KEY_METADATA].as_string() == session_key,
            )
            .limit(1)
        )
    ).scalar_one_or_none()


def _ownership_refusal(session: Session, identity: GatewayIdentity) -> GatewayRefusal | None:
    if session.user_id != identity.user.id:
        return GatewayRefusal(STATE_DENIED, REASON_SESSION_OWNER_MISMATCH)
    if session.project_id != identity.workspace_id:
        return GatewayRefusal(STATE_DENIED, REASON_SESSION_WORKSPACE_MISMATCH)
    return None


async def find_gateway_session(
    db: AsyncSession,
    identity: GatewayIdentity,
) -> Session | GatewayRefusal:
    """The existing shadow session for this key, or a refusal (hooks never create one)."""

    session = await _find_by_key(db, identity.session_key)
    if session is None:
        return GatewayRefusal(STATE_NEEDS_CONFIGURATION, REASON_SESSION_NOT_FOUND)
    refused = _ownership_refusal(session, identity)
    if refused is None:
        _attribute(session)
    return refused or session


def _attribute(session: Session) -> None:
    """The request's metric attribution from its session's run context (no extra read)."""
    from ..workflow_runs.octryx.attribution import use_for

    use_for(session)


async def get_or_create_gateway_session(
    db: AsyncSession,
    identity: GatewayIdentity,
    *,
    job_id: str = "",
) -> Session | GatewayRefusal:
    """The shadow session for this key, created on the first model call. Flushes only.

    Claude Code opens a session with parallel calls (main model and the small fast
    model), so on PostgreSQL the lookup-or-create runs under a transaction-scoped
    advisory lock on the key; one launcher session never becomes two rows.
    """

    if db.bind is not None and db.bind.dialect.name == "postgresql":
        await db.execute(text("SELECT pg_advisory_xact_lock(hashtext(:key))"), {"key": identity.session_key})
    session = await _find_by_key(db, identity.session_key)
    if session is not None:
        refused = _ownership_refusal(session, identity)
        if refused is None:
            _attribute(session)
        return refused or session
    session = Session(
        id=str(uuid.uuid4()),
        user_id=identity.user.id,
        project_id=identity.workspace_id,
        agent_type=EXTERNAL_AGENT_TYPE,
        status="active",
        origin="model_gateway",
        metadata_={
            "external_source": GATEWAY_EXTERNAL_SOURCE,
            "client": GATEWAY_CLIENT,
            SESSION_KEY_METADATA: identity.session_key,
            "oauth_grant_id": identity.grant_id,
            "work_item_key": identity.work_item_key or None,
            "summary": "octryx-claude session through the Octryx model gateway.",
        },
    )
    db.add(session)
    await db.flush()
    if identity.workflow_run_id:
        # A device job's session follows the run its job carries, after the same checks as an attach.
        from ..workflow_runs.octryx.attach import bind_device_session

        # ``job_id`` (registration): a teamwork item's job binds as its own session of the run (``octryx:<key>``).
        await bind_device_session(db, gateway_session=session, user=identity.user,
                                  workspace_id=identity.workspace_id, run_id=identity.workflow_run_id,
                                  job_id=job_id)
    _attribute(session)
    return session


__all__ = ["find_gateway_session", "get_or_create_gateway_session"]
