"""Cedar policy engine admin API, policy UX read model: catalog, picker entities, per-policy view.

Platform admins only (``policy_engine.require_admin``). Under ``/api/v1/admin/policy-engine``:

- ``GET /catalog`` — the builder's building blocks (actions, condition blocks, templates), keyed by schema version.
- ``GET /catalog/entities?type=&q=&limit=`` — Workspaces, users, roles, groups, named connections, tools, model
  aliases and connector families for the pickers; ``type`` repeats, ``q`` searches id and name.
- ``GET /policies?include_generated=`` — the per-policy view of the working version (open draft, version in
  review, else the published one), with the change state against the published version.
- ``GET /policies/references`` — per connector and per named connection, the working version's policies that name
  them (the connector cards link to the filtered list).
- ``GET /policy-sets/{version}/impact?hours=24`` — G8: what the version, as the open draft, would have blocked in
  live traffic (the draft shadow's counts per policy, point and action, hashed principals, redacted samples).
- ``GET /policy-sets/{version}/policies`` and ``GET /policy-sets/{version}/policies/{policy_id}`` — the same for
  one version, and one policy with its version history.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from ...db import get_db
from ...models import User
from ...services.policy_engine import store
from ...services.policy_engine.catalog import catalog_payload
from ...services.policy_engine.draft_shadow import draft_impact_view
from ...services.policy_engine.entity_listing import ENTITY_TYPES, list_entities
from ...services.policy_engine.policy_links import working_reference_counts
from ...services.policy_engine.policy_view import policies_view, policy_history, working_version
from .policy_engine import require_admin

router = APIRouter(prefix="/api/v1/admin/policy-engine", tags=["policy-engine"])


@router.get("/catalog")
async def get_catalog(_: User = Depends(require_admin)) -> dict[str, Any]:
    return catalog_payload()


@router.get("/catalog/entities")
async def get_catalog_entities(
    entity_type: list[str] | None = Query(default=None, alias="type"),
    q: str = Query(default="", max_length=100),
    limit: int = Query(default=500, ge=1, le=500),
    _: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    unknown = sorted(set(entity_type or ()) - set(ENTITY_TYPES))
    if unknown:
        raise HTTPException(status_code=422, detail={"code": "policy_entity_type_unknown", "types": unknown})
    return await list_entities(db, types=entity_type, query=q, limit=limit)


@router.get("/policies")
async def get_working_policies(
    include_generated: bool = False, _: User = Depends(require_admin), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return await policies_view(db, await working_version(db), include_generated=include_generated)


@router.get("/policies/references")
async def get_policy_references(_: User = Depends(require_admin), db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    return await working_reference_counts(db)


async def _version(db: AsyncSession, version: int):
    try:
        return await store.get_version(db, version)
    except store.PolicyStoreRefusalError as error:
        raise HTTPException(status_code=error.status, detail={"code": error.code}) from None


@router.get("/policy-sets/{version}/policies")
async def get_version_policies(
    version: int, include_generated: bool = False, _: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return await policies_view(db, await _version(db, version), include_generated=include_generated)


@router.get("/policy-sets/{version}/impact")
async def get_version_impact(
    version: int, hours: int = Query(default=24, ge=1, le=720), _: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """G8: what this version, as the open draft, would have blocked in live traffic (draft shadow)."""
    return await draft_impact_view(db, await _version(db, version), hours=hours)


@router.get("/policy-sets/{version}/policies/{policy_id:path}")
async def get_version_policy(
    version: int, policy_id: str, _: User = Depends(require_admin), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    view = await policies_view(db, await _version(db, version))
    item = next((entry for entry in view["items"] if entry["id"] == policy_id), None)
    if item is None:
        raise HTTPException(status_code=404, detail={"code": "policy_not_found"})
    return {**item, "history": await policy_history(db, policy_id)}


__all__ = ["router"]
