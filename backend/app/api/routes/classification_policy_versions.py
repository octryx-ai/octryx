"""Governed classification policy versions. Transport; logic in
``services/data_classification/policy_versions.py`` and ``policy_preview.py``.

- ``GET    /api/v1/admin/data-classification/policy/versions`` — platform admins: the open draft (effective rules,
  changes, generated-policy diff, affected Workspaces, last test run, review), the history, the approval rule.
- ``PUT    /api/v1/admin/data-classification/policy/draft`` ``{levels: [{level, rules}], default_level,
  level_catalog?: [{key, rank, label, color, description, models_allowed}], note}`` — create or replace the open
  draft (422 with a code for an invalid matrix or catalog, ``classification_level_in_use`` with the references for a
  retired level still in use; 409 while it is in review).
- ``DELETE /api/v1/admin/data-classification/policy/draft`` — withdraw the open draft or review.
- ``POST   /api/v1/admin/data-classification/policy/draft/submit`` ``{note}`` — run the saved test cases, open review.
- ``POST   /api/v1/admin/data-classification/policy/versions/{version}/approve`` — approve and publish (four-eyes).
- ``POST   /api/v1/admin/data-classification/policy/versions/{version}/reject`` ``{comment}``.
- ``POST   /api/v1/admin/data-classification/policy/versions/{version}/rollback`` — a draft from that version.
- ``GET    /api/v1/admin/data-classification/policy/generated?source=published|draft`` — the generated policies.
- ``GET    /api/v1/admin/data-classification/policy/workspaces`` — active Workspaces: level, its source, overrides.
- ``PUT    /api/v1/admin/data-classification/policy/workspaces/{id}/overrides`` ``{overrides}`` — stricter-only
  Workspace overrides (422 ``classification_override_looser`` with the reason).

Refusals: 403 for non-admins; ``{"detail": {"code", ...}}`` with 404/409/422 for lifecycle and validation refusals.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.data_classification import (
    policy_version_content,
    policy_version_drafts,
    policy_version_publish,
    policy_version_store,
)
from app.services.data_classification.policy_rules import ClassificationPolicyError

from ...db import get_db
from ...models import Approval, ClassificationPolicyVersion, McpServerRegistration, Project, User
from ...models.runtime.governed_revision import REVISION_STATE_IN_REVIEW
from ...services.access_control import _user_is_admin
from ...services.auth import get_current_user
from ...services.data_classification.effect_rules import EFFECT_CATALOG, EffectRuleError
from ...services.data_classification.level_catalog import content_registry
from ...services.data_classification.levels import LevelCatalogError, candidate_registry, catalog_of
from ...services.data_classification.policy_preview import (
    affected_workspaces,
    change_lines,
    generated_policies,
    policy_diff,
    workspace_levels,
)
from ...services.data_classification.workspace_overrides import OverrideError, set_workspace_overrides, stored_overrides
from ...services.governance.approval_rule import load_approval_rule

router = APIRouter(prefix="/api/v1/admin/data-classification/policy", tags=["data-classification"])

ADMIN_FORBIDDEN = "Platform admin role required"


async def require_admin(current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> User:
    if not await _user_is_admin(db, current_user.id):
        raise HTTPException(status_code=403, detail=ADMIN_FORBIDDEN)
    return current_user


def _refused(
    error: (policy_version_content.ClassificationVersionError | ClassificationPolicyError | LevelCatalogError
            | EffectRuleError),
) -> HTTPException:
    if isinstance(error, ClassificationPolicyError):
        return HTTPException(status_code=422, detail={"code": error.code, "path": error.path})
    if isinstance(error, LevelCatalogError | EffectRuleError):
        return HTTPException(status_code=422, detail={"code": error.code, "path": error.path,
                                                      **getattr(error, "details", {})})
    return HTTPException(status_code=error.status, detail={"code": error.code, **error.details})


async def _names(db: AsyncSession, ids: set[str]) -> dict[str, str]:
    wanted = {item for item in ids if item}
    if not wanted:
        return {}
    rows = (await db.execute(select(User).where(User.id.in_(wanted)))).scalars()
    return {row.id: row.display_name or row.username for row in rows}


def _iso(value: Any) -> str | None:
    return value.isoformat() if value else None


async def _version_view(db: AsyncSession, row: ClassificationPolicyVersion, *, base: dict[str, Any] | None,
                        viewer: User, names: dict[str, str]) -> dict[str, Any]:
    approval = await db.get(Approval, row.approval_id) if row.approval_id else None
    approver = str(approval.approved_by) if approval is not None and approval.status == "approved" else None
    in_review = (row.state == REVISION_STATE_IN_REVIEW and approval is not None
                 and approval.status in {"pending", "approved"})
    own = {str(row.created_by or ""), str(row.submitted_by or "")} - {""}
    self_allowed = await policy_version_publish.can_self_approve(db)
    return {
        "version": row.version,
        "state": row.state,
        "note": row.note,
        "digest": row.digest,
        "base_version": row.base_version,
        "default_level": (row.content or {}).get("default_level"),
        "changes": change_lines(base, row.content) if base is not None else list(row.changes or []),
        "test_report": row.test_report,
        "author": names.get(str(row.created_by or "")) if row.created_by else None,
        "submitted_by": names.get(str(row.submitted_by or "")) if row.submitted_by else None,
        "approved_by": names.get(approver) if approver else None,
        "created_at": _iso(row.created_at),
        "submitted_at": _iso(row.submitted_at),
        "published_at": _iso(row.published_at),
        "review": None if approval is None else {
            "status": approval.status,
            "comment": approval.reason or "",
            "can_approve": in_review and (self_allowed or viewer.id not in own),
        },
    }


async def _payload(db: AsyncSession, viewer: User) -> dict[str, Any]:
    rows = await policy_version_store.list_versions(db)
    names = await _names(db, {str(item) for row in rows for item in (row.created_by, row.submitted_by) if item}
                         | {str(row.published_by) for row in rows if row.published_by})
    for row in rows:
        if row.approval_id:
            approval = await db.get(Approval, row.approval_id)
            if approval is not None and approval.approved_by:
                names |= await _names(db, {str(approval.approved_by)})
    by_version = {row.version: row for row in rows}
    live = await policy_version_content.live_content(db)
    history = []
    for row in rows:
        base_row = by_version.get(row.base_version) if row.base_version else None
        base = None if row.state in {"published", "retired"} else dict(base_row.content) if base_row else live
        history.append(await _version_view(db, row, base=base, viewer=viewer, names=names))
    draft_row = await policy_version_store.open_draft(db)
    draft = None
    if draft_row is not None:
        base = await policy_version_store.base_content(db)
        policy = policy_version_content.content_policy(draft_row.content)
        lines = change_lines(base, draft_row.content)
        with candidate_registry(content_registry(draft_row.content)):
            draft_levels = [{"level": level, "rules": rules.to_dict()} for level, rules in policy.levels().items()]
        draft = {
            **await _version_view(db, draft_row, base=base, viewer=viewer, names=names),
            "levels": draft_levels,
            "level_catalog": catalog_of(content_registry(draft_row.content)),
            "effect_rules": list(draft_row.content.get("effect_rules") or []),
            "policy_diff": policy_diff(base, draft_row.content),
            "affected_workspaces": await affected_workspaces(db, lines),
        }
    published = await policy_version_store.published_version(db)
    return {
        "published_version": published.version if published is not None else None,
        "draft": draft,
        "versions": [item for item in history if item["state"] in {"published", "retired"}],
        "approval_rule": await load_approval_rule(db),
        "effect_catalog": list(EFFECT_CATALOG),
        "effect_rules": list((await policy_version_store.base_content(db)).get("effect_rules") or []),
        "mcp_servers": sorted({str(name) for name in (await db.execute(select(McpServerRegistration.name))).scalars()}),
        "self_approval": await policy_version_publish.can_self_approve(db),
        "can_edit": True,
    }


@router.get("/versions")
async def get_versions(user: User = Depends(require_admin), db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    return await _payload(db, user)


@router.put("/draft")
async def put_draft(body: dict[str, Any] = Body(...), user: User = Depends(require_admin),
                    db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    try:
        await policy_version_drafts.save_draft(db, levels=body.get("levels", []),
                                               default_level=body.get("default_level"),
                                  note=body.get("note"), actor_id=user.id, level_catalog=body.get("level_catalog"),
                                  effect_rules=body.get("effect_rules"))
    except (policy_version_content.ClassificationVersionError, ClassificationPolicyError, LevelCatalogError,
            EffectRuleError) as error:
        raise _refused(error) from None
    await db.commit()
    return await _payload(db, user)


@router.delete("/draft")
async def delete_draft(user: User = Depends(require_admin), db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    try:
        await policy_version_drafts.discard_draft(db, actor_id=user.id)
    except policy_version_content.ClassificationVersionError as error:
        raise _refused(error) from None
    await db.commit()
    return await _payload(db, user)


@router.post("/draft/submit")
async def submit_draft(body: dict[str, Any] = Body(default_factory=dict), user: User = Depends(require_admin),
                       db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    try:
        await policy_version_drafts.submit_draft(db, note=body.get("note"), actor_id=user.id)
    except policy_version_content.ClassificationVersionError as error:
        await db.commit()  # keeps the failing test report on the draft
        raise _refused(error) from None
    await db.commit()
    return await _payload(db, user)


@router.post("/versions/{version}/approve")
async def approve_version(version: int, user: User = Depends(require_admin),
                          db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    try:
        await policy_version_publish.approve_and_publish(db, version, actor_id=user.id)
    except policy_version_content.ClassificationVersionError as error:
        await db.rollback()
        raise _refused(error) from None
    await db.commit()
    return await _payload(db, user)


@router.post("/versions/{version}/reject")
async def reject_version(version: int, body: dict[str, Any] = Body(default_factory=dict),
                         user: User = Depends(require_admin), db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    try:
        await policy_version_publish.reject_version(db, version, comment=body.get("comment"), actor_id=user.id)
    except policy_version_content.ClassificationVersionError as error:
        raise _refused(error) from None
    await db.commit()
    return await _payload(db, user)


@router.post("/versions/{version}/rollback")
async def rollback_version(version: int, user: User = Depends(require_admin),
                           db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    try:
        await policy_version_publish.rollback_to(db, version, actor_id=user.id)
    except (policy_version_content.ClassificationVersionError, ClassificationPolicyError, LevelCatalogError) as error:
        raise _refused(error) from None
    await db.commit()
    return await _payload(db, user)


@router.get("/workspaces")
async def get_workspaces(_: User = Depends(require_admin), db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    """Every active Workspace with its level and where the level came from (own, default, none)."""
    from ...services.knowledge.projection.workspace_classification_default import workspace_classification_view

    rows = []
    for project_id, name, _level in await workspace_levels(db):
        view = await workspace_classification_view(db, project_id)
        project = await db.get(Project, project_id)
        rows.append({"id": project_id, "name": name, "level": view["effective"], "source": view["source"],
                     "overrides": stored_overrides(project.config if project is not None else None)})
    return {"workspaces": rows}


@router.put("/workspaces/{project_id}/overrides")
async def put_workspace_overrides(project_id: str, body: dict[str, Any] = Body(...),
                                  user: User = Depends(require_admin),
                                  db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    """A Workspace's stricter-only overrides; a looser value is 422 with the reason."""
    project = await db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Workspace not found")
    try:
        kept = await set_workspace_overrides(db, project=project, overrides=body.get("overrides", {}), actor_id=user.id)
    except OverrideError as error:
        raise HTTPException(status_code=422, detail={"code": error.code, "path": error.path,
                                                     "reason": error.reason}) from None
    await db.commit()
    return {"id": project_id, "overrides": kept}


@router.get("/generated")
async def get_generated(source: str = Query(default="published", pattern="^(published|draft)$"),
                        _: User = Depends(require_admin), db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    row = await policy_version_store.open_draft(db) if source == "draft" else None
    content = dict(row.content) if row is not None else await policy_version_store.base_content(db)
    return {"source": source if row is not None else "published", "policies": generated_policies(content)}


__all__ = ["router"]
