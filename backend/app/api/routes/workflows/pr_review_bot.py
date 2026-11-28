"""The PR review bot's settings per Workspace repository."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from ....db import get_db
from ....models import AuditLog, Project, User
from ....models.runtime.code_intelligence import CodeRepository
from ....services.access_control import get_project_role_for_user
from ....services.auth import get_current_user
from ....services.pr_review_bot.settings import (
    TRIGGERS,
    BotSettingsError,
    parse_settings,
    repository_of,
    settings_of,
    store_settings,
    workspace_repositories,
)

router = APIRouter(tags=["pr-review-bot"])
AUDIT_ACTION = "pr_review_bot.settings_changed"


def _refusal(reason: str, status: int, path: str = "") -> JSONResponse:
    return JSONResponse({"state": "denied", "reason": reason, **({"path": path} if path else {})}, status_code=status)


async def _webhook_configured(db: AsyncSession, project_id: str) -> bool:
    from ....models.integration.webhook import Webhook

    return (await db.execute(select(Webhook.id).where(
        Webhook.project_id == project_id, Webhook.source_type == "scm_pull_request",
        Webhook.is_active.is_(True)).limit(1))).first() is not None


async def _workspace(db: AsyncSession, user: User, project_id: str) -> tuple[Project | None, bool]:
    role = await get_project_role_for_user(db, user.id, project_id)
    project = await db.get(Project, project_id) if role is not None else None
    return project, role in {"admin", "owner"}


async def _editable(db: AsyncSession, user: User, project_id: str,
                    repository_id: str) -> tuple[CodeRepository | None, JSONResponse | None]:
    project, can_edit = await _workspace(db, user, project_id)
    if project is None:
        return None, _refusal("workspace_not_found", 404)
    record = (await db.execute(select(CodeRepository).where(
        CodeRepository.id == repository_id, CodeRepository.project_id == project_id))).scalar_one_or_none()
    if record is None or not repository_of(record):
        return None, _refusal("repository_not_found", 404)
    if not can_edit:
        return None, _refusal("workspace_admin_required", 403)
    return record, None


def _view(record: CodeRepository) -> dict[str, Any]:
    return {"id": record.id, "name": record.name, "repository": repository_of(record),
            "settings": settings_of(record).to_dict()}


@router.get("/api/v1/workspaces/{project_id}/pr-review-bot")
async def get_bot_settings(project_id: str, current_user: User = Depends(get_current_user),
                           db: AsyncSession = Depends(get_db)):
    project, can_edit = await _workspace(db, current_user, project_id)
    if project is None:
        return _refusal("workspace_not_found", 404)
    rows = [record for record in await workspace_repositories(db, project_id) if repository_of(record)]
    return {"repositories": [_view(record) for record in rows], "triggers": list(TRIGGERS), "can_edit": can_edit,
            "webhook_configured": await _webhook_configured(db, project_id)}


@router.put("/api/v1/workspaces/{project_id}/repositories/{repository_id}/pr-review-bot")
async def put_bot_settings(project_id: str, repository_id: str, body: dict[str, Any] = Body(...),
                           current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    record, refused = await _editable(db, current_user, project_id, repository_id)
    if refused is not None:
        return refused
    try:
        # Only the fields sent change (a panel that sent three fields reset fix_runs and the
        # size limits on every save); the stored settings, normalised, fill the rest.
        sent = body if isinstance(body, dict) else None
        settings = parse_settings({**settings_of(record).to_dict(), **sent} if sent is not None else body, strict=True)
    except BotSettingsError as error:
        return _refusal(error.reason, 400, error.path)
    store_settings(record, settings)
    flag_modified(record, "config_json")
    db.add(AuditLog(user_id=current_user.id, action=AUDIT_ACTION, resource_type="code_repository",
                    resource_id=record.id, project_id=record.project_id, details={"settings": settings.to_dict()}))
    await db.commit()
    return {**_view(record), "can_edit": True, "webhook_configured": await _webhook_configured(db, project_id)}


@router.post("/api/v1/workspaces/{project_id}/repositories/{repository_id}/pr-review-bot/sync")
async def sync_now(project_id: str, repository_id: str, current_user: User = Depends(get_current_user),
                   db: AsyncSession = Depends(get_db)):
    from ....services.pr_review_bot.sync import sync_repository

    record, refused = await _editable(db, current_user, project_id, repository_id)
    if refused is not None:
        return refused
    if not settings_of(record).on_sync():  # the saved trigger counts, not an unsaved form
        return _refusal("sync_not_switched_on", 409)
    db.add(AuditLog(user_id=current_user.id, action="pr_review_bot.sync_requested", resource_type="code_repository",
                    resource_id=record.id, project_id=record.project_id, details={}))
    await db.commit()
    reasons: dict[str, int] = {}
    try:
        outcomes = await sync_repository(db, record, reasons=reasons)
    except RuntimeError as error:  # the provider refused the read: named, never a 500
        return _refusal(f"pull_requests_unreadable: {error}"[:300], 502)
    return {"repository": repository_of(record), "outcomes": outcomes, "skipped_reasons": reasons}


@router.get("/api/v1/workspaces/{project_id}/pr-review-bot/review-seat")
async def get_review_seat(project_id: str, current_user: User = Depends(get_current_user),
                          db: AsyncSession = Depends(get_db)):
    from ....services.pr_review_bot.seat_choice import review_seat_on

    project, _can_edit = await _workspace(db, current_user, project_id)
    if project is None:
        return _refusal("workspace_not_found", 404)
    return {"enabled": await review_seat_on(db, project_id, current_user.id)}


@router.put("/api/v1/workspaces/{project_id}/pr-review-bot/review-seat")
async def put_review_seat(project_id: str, body: dict[str, Any] = Body(...),
                          current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    from ....services.pr_review_bot.seat_choice import set_review_seat

    project, _can_edit = await _workspace(db, current_user, project_id)
    if project is None:
        return _refusal("workspace_not_found", 404)
    if not isinstance(body, dict) or not isinstance(body.get("enabled"), bool):
        return _refusal("enabled_not_a_boolean", 400)
    await set_review_seat(db, project, current_user.id, body["enabled"])
    db.add(AuditLog(user_id=current_user.id, action="pr_review_bot.review_seat_changed", resource_type="project",
                    resource_id=project_id, details={"enabled": body["enabled"]}))
    await db.commit()
    return {"enabled": body["enabled"]}


@router.get("/api/v1/workspaces/{project_id}/pr-review-bot/rule-proposals")
async def get_rule_proposals(project_id: str, current_user: User = Depends(get_current_user),
                             db: AsyncSession = Depends(get_db)):
    """The team rules ``@octryx ignore`` proposed, newest first; members read, admins decide."""
    from ....services.pr_review_bot.rule_proposals import proposals

    project, can_edit = await _workspace(db, current_user, project_id)
    if project is None:
        return _refusal("workspace_not_found", 404)
    return {"proposals": list(reversed(proposals(project))), "can_edit": can_edit}


@router.post("/api/v1/workspaces/{project_id}/pr-review-bot/rule-proposals/{proposal_id}/{decision}")
async def decide_rule_proposal(project_id: str, proposal_id: str, decision: str,
                               body: dict[str, Any] | None = Body(default=None),
                               current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """``accept`` (optionally with the edited ``rule`` text) appends the rule to the repository's code style rules;
    ``reject`` closes the proposal. Workspace admins and owners only; audited."""
    from ....services.pr_review_bot.rule_proposals import decide

    if decision not in ("accept", "reject"):
        return _refusal("decision_unknown", 404)
    project, can_edit = await _workspace(db, current_user, project_id)
    if project is None:
        return _refusal("workspace_not_found", 404)
    if not can_edit:
        return _refusal("workspace_admin_required", 403)
    rule = str(dict(body or {}).get("rule") or "")
    decided = await decide(db, project, proposal_id, accept=decision == "accept", actor_id=current_user.id, rule=rule)
    if isinstance(decided, str):
        return _refusal(decided, 404 if decided.endswith("not_found") else 409)
    db.add(AuditLog(user_id=current_user.id, action=f"pr_review_bot.rule_{decision}ed", resource_type="project",
                    resource_id=project_id, details={"proposal": decided}))
    await db.commit()
    return {"proposal": decided}
