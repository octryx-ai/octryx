"""Content security: Detect → Decide → Act for content. Transport only; the logic is in
``services/content_security``. Platform admins only.

- ``GET  /api/v1/admin/content-security`` — the coverage matrix (surfaces × categories → outcome), the pipeline
  counts, the policy engine mode, where a detector edit goes (``edit_target``, as on Policies) and the approved
  models (read-only; set per model in Runtime).
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from ...db import get_db
from ...models import User
from ...services.content_security.coverage import coverage
from ...services.data_classification.levels import level_registry
from ...services.data_classification.policy_matrix import load_classification_policy
from ...services.model_gateway.data_policy.effects import gateway_aliases
from ...services.policy_engine.policy_edits import open_or_published
from ...services.policy_engine.policy_view import edit_target
from ...services.policy_engine.runtime import alias_approvals
from .policy_engine import require_admin

router = APIRouter(prefix="/api/v1/admin/content-security", tags=["content-security"])


async def approved_models(db: AsyncSession) -> list[dict[str, Any]]:
    """Every gateway model: cleared up to (its data-policy class), approved categories, the levels that may use it."""
    approvals = await alias_approvals(db)
    allowlists = (await load_classification_policy(db)).model_allowlists()
    registry = level_registry()
    rows = []
    for alias, data_policy_class in await gateway_aliases(db):
        cleared = registry.rank(data_policy_class) or 0
        levels = [level.key for level in registry.levels if level.models_allowed and level.rank <= cleared
                  and (level.key not in allowlists or alias in allowlists[level.key])]
        rows.append({"alias": alias, "cleared_up_to": data_policy_class,
                     "approved_for": sorted(approvals.get(alias, ())), "levels": levels})
    return rows


@router.get("")
async def get_content_security(_: User = Depends(require_admin), db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    return {
        "coverage": await coverage(db),
        "edit_target": edit_target(await open_or_published(db)),
        "approved_models": await approved_models(db),
        "levels": [{"key": level.key, "label": level.label, "color": level.color} for level in level_registry().levels],
    }


__all__ = ["router"]
