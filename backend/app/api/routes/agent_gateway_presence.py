"""Agent gateway: session registration and the presence read model.

Transport only; decisions live in ``services/agent_gateway`` (``presence``, ``seat_policy``,
``seat_credential``).

- ``POST /api/v1/agent-gateway/sessions/register`` — the launcher, with its normal gateway token and
  session headers, registers the session before Claude Code starts. Body ``{profile, branch?, client?,
  client_version?, job_id?}`` (``job_id``: a device job's, so a teamwork item's session binds as its own); the
  work item comes from ``X-Octryx-Work-Item``. ``seat`` is refused with
  the Workspace's fixed reason (``seat_mode_forbidden``, ``seat_requires_governed_routing``,
  ``seat_classification_too_sensitive``, ``seat_classification_unresolved``, ``policy_invalid``); the
  launcher then does not start. A ``seat`` body with ``engine: codex`` (a Codex seat on the person's own ChatGPT
  login) is decided by ``codex_seat_mode`` instead (``codex_seat_mode_forbidden``) and needs the Codex engine
  allowed (``engine_not_allowed_in_workspace``); it gets the same session-bound credential. A ``seat`` answer
  carries the session-bound credential once. With
  ``purpose: work_item_analysis`` (``octryx-claude analyze``) the session is a seat analysis session pinned to
  the work item (``services/work_item_analysis/seat_session``), or is refused with that module's reason. Any other
  session with a Work item attaches to the item's active run (``workflow_runs/octryx/launch``): the answer carries
  ``workflow_run`` (the contract the launcher's banner shows) or ``workflow_run_attach`` (why not). A device job's
  session (``X-Octryx-Workflow-Run``) is bound to its job's run here; a run it may not follow refuses the
  registration with the attach reason (``launch.device_run_answer``).
- ``GET /api/v1/agent-gateway/workspaces`` — the launcher's login (gateway token only) lists the Workspaces it
  may use, so ``--workspace`` accepts a name.
- ``GET /api/v1/agent-gateway/presence?project_id=`` — the UI's "Connected clients": one entry per person and
  device (``id``, ``sessions``), seven-day retention. Workspace membership is required (403 otherwise);
  ``allowance`` is filled only for Workspace admins/owners and platform admins.
- ``DELETE /api/v1/agent-gateway/presence/{entry_id}?project_id=`` — removes one entry (all its session rows):
  your own, or anyone's as a Workspace admin/owner or platform admin. Audited; 404 for an entry you cannot see.
"""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from ...db import get_db
from ...models import User
from ...services.access_control import require_project_scope
from ...services.agent_gateway.contract import (
    GATEWAY_CLIENT,
    HEADER_GATEWAY_REASON,
    HEADER_GATEWAY_STATE,
    STATE_DENIED,
)
from ...services.agent_gateway.engine_keys import ENGINE_CODEX, REASON_ENGINE_NOT_ALLOWED, SESSION_ENGINE_KEY
from ...services.agent_gateway.engine_policy import effective_engine
from ...services.agent_gateway.identity import GatewayRefusal, resolve_gateway_identity, resolve_gateway_login
from ...services.agent_gateway.presence import (
    REASON_ALREADY_REGISTERED,
    list_presence,
    register_session,
    session_key_hash,
)
from ...services.agent_gateway.presence_devices import remove_presence_entry
from ...services.agent_gateway.seat_credential import HEADER_SEAT_CREDENTIAL, PROFILE_GOVERNED, PROFILE_SEAT
from ...services.agent_gateway.seat_policy import workspace_seat_decision
from ...services.agent_gateway.sessions import get_or_create_gateway_session
from ...services.auth import get_current_user
from ...services.devices.run_trace import stamp_gateway_session
from ...services.policy_engine.request_principal import load_seat_principal
from ...services.project.service import get_project_access_details
from ...services.work_item_analysis.seat_session import pin_session, registration_refusal
from ...services.workflow_runs.octryx.launch import device_run_answer, launch_answer

router = APIRouter(tags=["agent-gateway"])

MAX_REGISTER_BODY_BYTES = 4 * 1024
REASON_BODY_INVALID = "request_body_invalid"
MCP_AUTH_CACHE_CLEARED_KEY = "mcp_auth_cache_cleared"


def _refusal(state: str, reason: str, status: int) -> JSONResponse:
    return JSONResponse(
        {"state": state, "reason": reason},
        status_code=status,
        headers={HEADER_GATEWAY_STATE: state, HEADER_GATEWAY_REASON: reason},
    )


async def _small_json(request: Request) -> dict[str, Any] | None:
    raw = bytearray()
    async for chunk in request.stream():
        raw.extend(chunk)
        if len(raw) > MAX_REGISTER_BODY_BYTES:
            return None
    try:
        body = json.loads(bytes(raw) or b"{}")
    except ValueError:
        return None
    return body if isinstance(body, dict) else None


async def _keeps_sessions_read_only(db: AsyncSession, workspace_id: str | None, user_id: str | None = None) -> bool:
    """A strict Workspace (free_sessions read_only) or a viewer in it: sessions read only."""
    from ...services.agent_gateway.role_modes import CEILING_READ_ONLY, session_ceiling  # noqa: PLC0415

    if not workspace_id:
        return False
    return await session_ceiling(db, user_id=user_id, workspace_id=workspace_id) == CEILING_READ_ONLY


async def _seat_refusal(db: AsyncSession, identity, body: dict[str, Any]) -> JSONResponse | None:
    """A seat registration's refusal, or ``None`` when the Workspace allows the seat."""
    # ``engine: codex``: a Codex seat (the person's own ChatGPT login) is decided by ``codex_seat_mode`` and needs
    # the Codex engine allowed; any other registration keeps the Claude seat's decision (``seat_mode``).
    codex = body.get("engine") == ENGINE_CODEX
    if codex and ENGINE_CODEX not in (await effective_engine(
            db, user_id=identity.user.id, workspace_id=identity.workspace_id)).allowed:
        return _refusal(STATE_DENIED, REASON_ENGINE_NOT_ALLOWED, 403)
    decision = await workspace_seat_decision(db, identity.workspace_id, principal=await load_seat_principal(
        identity.user.id, session_id=f"launch:{session_key_hash(identity.session_key)}", client=GATEWAY_CLIENT),
        codex=codex)
    if not decision.allowed:
        return _refusal(STATE_DENIED, decision.reason, 403)
    return None


def _note_mcp_auth_cache_cleared(session, body: dict[str, Any]) -> None:
    # The launcher removed Claude Code's "needs authentication" mark for the platform server (a mark a broken turn
    # leaves hides the platform tools for the following turns): kept on the session and counted.
    from ...services.observability import device_report_metrics  # noqa: PLC0415

    session.metadata_ = {**dict(session.metadata_ or {}), MCP_AUTH_CACHE_CLEARED_KEY: True}
    profile = body.get("profile")
    device_report_metrics.mcp_auth_cache_cleared(profile if profile in (PROFILE_GOVERNED, PROFILE_SEAT) else "other")


async def _attach_run(db: AsyncSession, identity, session, answer: dict[str, Any], *, analysed,
                      job_id: str) -> JSONResponse | None:
    """Bind the session to its purpose: a Work item analysis, its device job's run, or the Work item's active run."""
    if analysed is not None:
        pin_session(session, analysed)
        answer["purpose"] = "work_item_analysis"
    elif identity.workflow_run_id:
        # A device job's session follows the run its job carries from registration, or does not start.
        answer.update(await device_run_answer(db, session=session, user=identity.user,
                                              workspace_id=identity.workspace_id, run_id=identity.workflow_run_id,
                                              job_id=job_id))
        if answer["workflow_run_attach"]["state"] != "attached":
            return _refusal(STATE_DENIED, answer["workflow_run_attach"]["reason"], 403)
    else:
        # A session started for a Work item follows its active run from launch (the terminal shows the banner).
        answer.update(await launch_answer(db, session=session, user=identity.user, workspace_id=identity.workspace_id,
                                          work_item_key=identity.work_item_key or ""))
    return None


@router.post("/sessions/register")
async def register_gateway_session(request: Request, db: AsyncSession = Depends(get_db)):
    identity = await resolve_gateway_identity(db, request.headers)
    if isinstance(identity, GatewayRefusal):
        return _refusal(identity.state, identity.reason, identity.http_status)
    body = await _small_json(request)
    if body is None:
        return _refusal(STATE_DENIED, REASON_BODY_INVALID, 400)
    if body.get("profile") == PROFILE_SEAT and (refused := await _seat_refusal(db, identity, body)) is not None:
        return refused
    purpose_refusal, analysed = await registration_refusal(
        db, workspace_id=identity.workspace_id, work_item_key=identity.work_item_key or "", body=body
    )
    if purpose_refusal:
        return _refusal(STATE_DENIED, purpose_refusal, 403)
    job_id = str(body.get("job_id") or "")[:64]  # a device job's: its thread may be a teamwork item's
    session = await get_or_create_gateway_session(db, identity, job_id=job_id)
    if isinstance(session, GatewayRefusal):
        return _refusal(session.state, session.reason, session.http_status)
    answer = await register_session(db, identity=identity, session=session, body=body)
    if not isinstance(answer, str) and body.get("engine") == ENGINE_CODEX:
        # The engine the launcher runs (the device job sits on the platform session, the model
        # talks through this gateway session, so the run contract kept Claude's tool names for a Codex model).
        session.metadata_ = {**dict(session.metadata_ or {}), SESSION_ENGINE_KEY: ENGINE_CODEX}
    if isinstance(answer, str):
        return _refusal(STATE_DENIED, answer, 409 if answer == REASON_ALREADY_REGISTERED else 400)
    if body.get("mcp_auth_cache_cleared") is True:
        _note_mcp_auth_cache_cleared(session, body)
    from ...services.workflow_runs.review.seat_control import mark_review_session

    # The independent reviewer's seat turn: a session without tools that reads its one request (``review.seat``).
    await mark_review_session(db, session, job_id, identity.user.id)
    # A device turn's gateway session names its job and turn, so the chat trace lists the turn's calls.
    await stamp_gateway_session(db, session, job_id, identity.user.id)
    if (refused := await _attach_run(db, identity, session, answer, analysed=analysed, job_id=job_id)) is not None:
        return refused
    if "workflow_run" not in answer and await _keeps_sessions_read_only(db, identity.workspace_id,
                                                                        identity.user.id):
        from ...services.workflow_runs.octryx.agent_view import outside_run_agent

        # A strict Workspace (agent_gateway_policy.free_sessions = "read_only"): outside a run the session reads and
        # works as the Assistant. Everywhere else it follows the person's permission mode like plain Claude Code
        # and gets no read-only instructions that would make the model refuse what is allowed.
        answer["platform_agent"] = await outside_run_agent(db)
    await db.commit()
    if "seat_credential" in answer:
        answer["credential_header"] = HEADER_SEAT_CREDENTIAL
    return JSONResponse(answer, headers={"cache-control": "no-store"})


@router.get("/workspaces")
async def gateway_workspaces(request: Request, db: AsyncSession = Depends(get_db)):
    """The Workspaces the launcher's login may use, for ``octryx-claude --workspace <name>``.

    Only the gateway token is needed (no session or Workspace header): the caller's member Workspaces, narrowed by
    the grant's project binding. ``{items: [{id, name}]}``, by name.
    """
    login = await resolve_gateway_login(db, request.headers)
    if isinstance(login, GatewayRefusal):
        return _refusal(login.state, login.reason, login.http_status)
    user, context = login
    bound = set(context.bound_project_ids) if context.bound_project_ids is not None else None
    items = [
        {"id": str(entry["id"]), "name": str(entry.get("name") or "")}
        for entry in await get_project_access_details(user.id, db)
        if bound is None or str(entry["id"]) in bound
    ]
    return {"items": sorted(items, key=lambda item: (item["name"].lower(), item["id"]))}


@router.get("/presence")
async def workspace_presence(
    project_id: str = Query(..., min_length=1, max_length=64),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    scope = await require_project_scope(db, current_user.id, project_id)
    return await list_presence(db, project_id=scope.project_id, include_allowance=scope.project_admin)


@router.delete("/presence/{entry_id}")
async def remove_workspace_presence(
    entry_id: str = Path(..., pattern=r"^[0-9a-f]{32}$"),
    project_id: str = Query(..., min_length=1, max_length=64),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    scope = await require_project_scope(db, current_user.id, project_id)
    removed = await remove_presence_entry(db, project_id=scope.project_id, entry=entry_id, actor_id=current_user.id,
                                          may_remove_others=scope.project_admin)
    if not removed:
        raise HTTPException(status_code=404, detail="presence_entry_not_found")
    await db.commit()
    return {"state": "removed", "id": entry_id, "sessions": removed}


__all__ = ["router"]
