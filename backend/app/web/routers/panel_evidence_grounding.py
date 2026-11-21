"""Admin panel: the evidence-grounding setting ``agent.evidence_grounding_config``.

Admin-only. ``GET`` returns the effective high-risk agent types with their source (``default`` seed
list or ``configured``). ``PUT`` replaces the list after validation and records the audit row
``admin.evidence_grounding_config.updated``; an unknown key (``unknown_setting``) or an invalid list
(``invalid_high_risk_agent_types``) answers 422 and nothing is stored.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.services.admin.governance.admin_config_audit_service import record_admin_config_audit
from app.services.system_config.evidence_domains import (
    EVIDENCE_GROUNDING_CONFIG_KEY,
    get_evidence_grounding_config,
    set_evidence_grounding_config,
)
from app.web._helpers.api_guards import _require_admin_api

router = APIRouter()

_PATH = "/chat/api/panel/evidence-grounding"


def _payload(config: dict[str, Any]) -> dict[str, Any]:
    return {**config, "high_risk_agent_types": sorted(config["high_risk_agent_types"])}


@router.get(_PATH)
async def panel_get_evidence_grounding(request: Request, db: AsyncSession = Depends(get_db)):
    await _require_admin_api(request, db)
    return JSONResponse(_payload(await get_evidence_grounding_config(db)))


@router.put(_PATH)
async def panel_put_evidence_grounding(
    request: Request,
    payload: dict[str, Any] = Body(...),
    db: AsyncSession = Depends(get_db),
):
    admin = await _require_admin_api(request, db)
    before = _payload(await get_evidence_grounding_config(db))
    after = _payload(await set_evidence_grounding_config(db, payload, updated_by=admin.id))
    record_admin_config_audit(
        db,
        actor_user_id=admin.id,
        action="admin.evidence_grounding_config.updated",
        resource_type="system_config",
        resource_id=EVIDENCE_GROUNDING_CONFIG_KEY,
        before={"high_risk_agent_types": before["high_risk_agent_types"]},
        after={"high_risk_agent_types": after["high_risk_agent_types"]},
    )
    await db.commit()
    return JSONResponse(after)
