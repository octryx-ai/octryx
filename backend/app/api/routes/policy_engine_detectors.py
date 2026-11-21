"""Cedar policy engine admin API, content detectors. Platform admins only; transport only.

Under ``/api/v1/admin/policy-engine``:

- ``GET  /content-detectors?version=`` — the Detectors tab: built-in and custom categories and detectors with the
  policies that use them, for ``version`` (default: the open draft, else the published version).
- ``GET  /policy-sets/{version}/detectors`` — the custom definitions of a version.
- ``PUT  /policy-sets/{version}/detectors`` ``{categories, detectors, note?}`` with ``If-Match: <digest>`` — save
  them into the draft (a new draft from the published version when none is open). 422
  ``{"detail": {"code": "content_detectors_invalid", "issues"}}``; 409/428 like a policy edit.
- ``POST /content-detectors/preview`` ``{text, detectors?, workspace_id?, mask?, mask_style?}`` — what the
  detectors find in a synthetic sample, with unsaved ``detectors`` definitions when given (the drawer's test
  field). The sample is never stored or logged.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.content_detection.custom_definitions import DetectorSetError
from app.services.content_detection.custom_validation import check_detector_set

from ...db import get_db
from ...models import User
from ...schemas.core.workspace_ref import OptionalWorkspaceId
from ...services.access_control import require_existing_workspace
from ...services.content_detection.preview import MAX_PREVIEW_CHARS, preview
from ...services.content_detection.registry import detector_set_for
from ...services.content_detection.vocabulary import MASK_STYLES
from ...services.policy_engine import store
from ...services.policy_engine.custom_policies import CustomPolicyError
from ...services.policy_engine.detector_edits import detector_catalog, put_detectors
from ...services.policy_engine.policy_edits import PolicyEditError, open_or_published
from .policy_engine import require_admin

router = APIRouter(prefix="/api/v1/admin/policy-engine", tags=["policy-engine"])


class DetectorsRequest(BaseModel):
    categories: list[dict[str, Any]] = Field(default_factory=list, max_length=50)
    detectors: list[dict[str, Any]] = Field(default_factory=list, max_length=100)
    note: str | None = Field(default=None, max_length=500)


class PreviewRequest(BaseModel):
    text: str = Field(default="", max_length=MAX_PREVIEW_CHARS)
    detectors: dict[str, Any] | None = None
    workspace_id: OptionalWorkspaceId = Field(default=None, max_length=64)
    mask: list[str] | None = Field(default=None, max_length=100)
    mask_style: str | None = Field(default=None, max_length=20)


def _invalid(error: DetectorSetError | CustomPolicyError) -> HTTPException:
    return HTTPException(status_code=422, detail={"code": error.code, "issues": error.issues})


@router.get("/content-detectors")
async def get_detector_catalog(
    version: int | None = Query(default=None, ge=1), _: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    if version is None:
        return detector_catalog(await open_or_published(db))
    try:
        return detector_catalog(await store.get_version(db, version))
    except store.PolicyStoreRefusalError as error:
        raise HTTPException(status_code=error.status, detail={"code": error.code}) from None


@router.get("/policy-sets/{version}/detectors")
async def get_detectors(
    version: int, _: User = Depends(require_admin), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    try:
        row = await store.get_version(db, version)
    except store.PolicyStoreRefusalError as error:
        raise HTTPException(status_code=error.status, detail={"code": error.code}) from None
    return {"version": row.version, "digest": row.digest, **store.detector_definitions(row).to_json()}


@router.put("/policy-sets/{version}/detectors")
async def save_detectors(
    version: int, body: DetectorsRequest, if_match: str | None = Header(default=None),
    user: User = Depends(require_admin), db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    try:
        row = await put_detectors(db, version, {"categories": body.categories, "detectors": body.detectors},
                                  if_match=if_match, note=body.note, actor_id=user.id)
    except (DetectorSetError, CustomPolicyError) as error:
        raise _invalid(error) from None
    except (store.PolicyStoreRefusalError, PolicyEditError) as error:
        raise HTTPException(status_code=error.status, detail={"code": error.code, **error.details}) from None
    await db.commit()
    return store.serialize_version(row)


@router.post("/content-detectors/preview")
async def preview_detectors(
    body: PreviewRequest, _: User = Depends(require_admin), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    await require_existing_workspace(db, body.workspace_id)
    if body.mask_style is not None and body.mask_style not in MASK_STYLES:
        raise HTTPException(status_code=422, detail={"code": "mask_style_invalid"})
    try:
        definitions = (check_detector_set(body.detectors) if body.detectors is not None
                       else store.detector_definitions(await open_or_published(db)))
    except DetectorSetError as error:
        raise _invalid(error) from None
    detectors = detector_set_for(definitions, body.workspace_id)
    return preview(body.text, detectors, mask=body.mask, style=body.mask_style)


__all__ = ["router"]
