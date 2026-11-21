"""Cedar policy engine admin API: platform admins only. Transport; logic in ``services/policy_engine``.

- ``GET  /api/v1/admin/policy-engine/status`` — mode, engine, published custom version, baseline digest,
  counters, latency, decision-log buffer.
- ``PUT  /api/v1/admin/policy-engine/mode`` ``{mode}`` — ``off`` | ``shadow`` | ``enforce`` (``enforce``: 409 until
  the enforce readiness checks pass).
- ``GET  /api/v1/admin/policy-engine/schema`` — the Cedar schema text, version and actions.
- ``GET  /api/v1/admin/policy-engine/baseline`` — the generated baseline (text + digest).
- ``GET  /api/v1/admin/policy-engine/decisions`` — the decision log, filterable, newest first.
- ``POST /api/v1/admin/policy-engine/validate`` ``{policies}`` — check custom policies without saving.
- ``GET|POST /api/v1/admin/policy-engine/policy-sets`` and ``GET|PUT|PATCH /policy-sets/{version}``,
  ``POST /policy-sets/{version}/submit|publish|retire|rollback`` — the governed custom versions. ``PUT`` saves the
  whole text and requires ``If-Match: <digest>`` (428 without, 409 ``policy_set_draft_conflict`` when stale);
  ``PATCH`` ``{note}`` changes only the change note. One version
  carries its ``review`` (requester, status, comment, approver candidates, whether the viewer may approve);
  the list carries author and reviewer names.

Refusals: 403 for non-admins; 422 ``{"detail": {"code", "issues"}}`` for policies that do not validate; 404/409
``{"detail": {"code", ...}}`` for lifecycle refusals.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ...db import get_db
from ...models import User
from ...services.access_control import _user_is_admin
from ...services.auth import get_current_user
from ...services.policy_engine import store, store_publish
from ...services.policy_engine.admin import PolicyEngineSettingError, engine_status, set_mode
from ...services.policy_engine.baseline import load_baseline
from ...services.policy_engine.custom_policies import CustomPolicyError, check_custom_policies
from ...services.policy_engine.decision_log import query_decisions, serialize_decision
from ...services.policy_engine.policy_edits import PolicyEditError, save_set
from ...services.policy_engine.review import history_rows, review_view
from ...services.policy_engine.runtime import refresh_policy_runtime
from ...services.policy_engine.schema import ACTIONS, SCHEMA_VERSION, schema_text

router = APIRouter(prefix="/api/v1/admin/policy-engine", tags=["policy-engine"])

ADMIN_FORBIDDEN = "Platform admin role required"


class ModeRequest(BaseModel):
    mode: str = Field(min_length=1, max_length=20)


class PoliciesRequest(BaseModel):
    policies: str = Field(default="", max_length=200_000)
    note: str | None = Field(default=None, max_length=500)


class NoteRequest(BaseModel):
    note: str | None = Field(default=None, max_length=500)


class PublishRequest(BaseModel):
    governance_approval_id: str | None = Field(default=None, max_length=36)
    # The single-step publish under the ``single_admin`` approval rule: approve the own pending review first.
    self_approve: bool = False


async def require_admin(
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> User:
    if not await _user_is_admin(db, current_user.id):
        raise HTTPException(status_code=403, detail=ADMIN_FORBIDDEN)
    return current_user


def _invalid(error: CustomPolicyError) -> HTTPException:
    return HTTPException(status_code=422, detail={"code": error.code, "issues": error.issues})


def _refused(error: store.PolicyStoreRefusalError | PolicyEngineSettingError | PolicyEditError) -> HTTPException:
    return HTTPException(status_code=error.status, detail={"code": error.code, **error.details})


@router.get("/status")
async def get_status(_: User = Depends(require_admin), db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    return await engine_status(db)


@router.put("/mode")
async def put_mode(
    body: ModeRequest, user: User = Depends(require_admin), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    try:
        await set_mode(db, mode=body.mode, actor_id=user.id)
    except PolicyEngineSettingError as error:
        raise _refused(error) from None
    await db.commit()
    return await engine_status(db)


@router.get("/schema")
async def get_schema(_: User = Depends(require_admin)) -> dict[str, Any]:
    return {"version": SCHEMA_VERSION, "schema": schema_text(), "actions": list(ACTIONS)}


@router.get("/baseline")
async def get_baseline(_: User = Depends(require_admin), db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    baseline = await load_baseline(db)
    return {"digest": baseline.digest, "policies": baseline.text, "workspaces": baseline.workspaces,
            "matrix_state": baseline.matrix_state, "schema_version": SCHEMA_VERSION}


@router.get("/decisions")
async def get_decisions(
    point: str | None = Query(default=None, max_length=40),
    outcome: str | None = Query(default=None, max_length=20),
    workspace_id: str | None = Query(default=None, max_length=64),
    action: str | None = Query(default=None, max_length=40),
    policy_id: str | None = Query(default=None, max_length=200),
    since: datetime | None = None,
    until: datetime | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    _: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    rows, total = await query_decisions(db, point=point, outcome=outcome, workspace_id=workspace_id, action=action,
                                        policy_id=policy_id, since=since, until=until, limit=limit, offset=offset)
    return {"items": [serialize_decision(row) for row in rows], "total": total, "limit": limit, "offset": offset}


@router.post("/validate")
async def validate_policies(body: PoliciesRequest, _: User = Depends(require_admin)) -> dict[str, Any]:
    try:
        checked = check_custom_policies(body.policies)
    except CustomPolicyError as error:
        return {"valid": False, "code": error.code, "issues": error.issues}
    return {"valid": True, "policy_ids": list(checked.ids), "digest": checked.digest}


@router.get("/policy-sets")
async def list_policy_sets(_: User = Depends(require_admin), db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    rows = await store.list_versions(db)
    items = await history_rows(db, rows, [store.serialize_version(row, include_text=False) for row in rows])
    return {"items": items, "count": len(rows)}


@router.post("/policy-sets", status_code=201)
async def create_policy_set(
    body: PoliciesRequest, user: User = Depends(require_admin), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    try:
        row = await store.create_draft(db, text=body.policies, note=body.note, actor_id=user.id)
    except CustomPolicyError as error:
        raise _invalid(error) from None
    await db.commit()
    return store.serialize_version(row)


async def _version(db: AsyncSession, version: int):
    try:
        return await store.get_version(db, version)
    except store.PolicyStoreRefusalError as error:
        raise _refused(error) from None


@router.get("/policy-sets/{version}")
async def get_policy_set(
    version: int, user: User = Depends(require_admin), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    row = await _version(db, version)
    return {**store.serialize_version(row), "review": await review_view(db, row, viewer_id=user.id)}


@router.put("/policy-sets/{version}")
async def save_policy_set(
    version: int, body: PoliciesRequest, if_match: str | None = Header(default=None),
    user: User = Depends(require_admin), db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    row = await _version(db, version)
    try:
        await save_set(db, row, text=body.policies, note=body.note, if_match=if_match, actor_id=user.id)
    except CustomPolicyError as error:
        raise _invalid(error) from None
    except (store.PolicyStoreRefusalError, PolicyEditError) as error:
        raise _refused(error) from None
    await db.commit()
    return store.serialize_version(row)


@router.patch("/policy-sets/{version}")
async def save_policy_set_note(
    version: int, body: NoteRequest, user: User = Depends(require_admin), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    row = await _version(db, version)
    try:
        await store.save_note(db, row, note=body.note, actor_id=user.id)
    except store.PolicyStoreRefusalError as error:
        raise _refused(error) from None
    await db.commit()
    return store.serialize_version(row)


@router.post("/policy-sets/{version}/submit")
async def submit_policy_set(
    version: int, user: User = Depends(require_admin), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    row = await _version(db, version)
    try:
        approval = await store.submit_version(db, row, actor_id=user.id)
    except CustomPolicyError as error:
        raise _invalid(error) from None
    except store.PolicyStoreRefusalError as error:
        raise _refused(error) from None
    await db.commit()
    return {**store.serialize_version(row), "governance_approval_id": approval.id}


@router.post("/policy-sets/{version}/publish")
async def publish_policy_set(
    version: int, body: PublishRequest, user: User = Depends(require_admin), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    row = await _version(db, version)
    try:
        gate = await store_publish.publish_version(db, row, approval_id=body.governance_approval_id, actor_id=user.id,
                                          self_approve=body.self_approve)
    except store.PolicyStoreRefusalError as error:
        raise _refused(error) from None
    await db.commit()
    await refresh_policy_runtime(db)
    return {**store.serialize_version(row), "approval_gate": gate.as_dict()}


@router.post("/policy-sets/{version}/retire")
async def retire_policy_set(
    version: int, user: User = Depends(require_admin), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    row = await _version(db, version)
    try:
        await store.retire_version(db, row, actor_id=user.id)
    except store.PolicyStoreRefusalError as error:
        raise _refused(error) from None
    await db.commit()
    await refresh_policy_runtime(db)
    return store.serialize_version(row)


@router.post("/policy-sets/{version}/rollback", status_code=201)
async def rollback_policy_set(
    version: int, user: User = Depends(require_admin), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    try:
        row = await store.rollback_to(db, version, actor_id=user.id)
    except CustomPolicyError as error:
        raise _invalid(error) from None
    except store.PolicyStoreRefusalError as error:
        raise _refused(error) from None
    await db.commit()
    return store.serialize_version(row)


__all__ = ["router"]
