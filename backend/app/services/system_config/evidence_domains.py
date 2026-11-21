"""Evidence-grounding configuration (``agent.evidence_grounding_config``).

The live setting is ``high_risk_agent_types``: agent types whose turns always obey the
evidence-grounded answer contract. Without a stored value the seed list
(``DEFAULT_HIGH_RISK_AGENT_TYPES``) applies; the admin UI (runtime settings, "Evidence grounding",
``/chat/api/panel/evidence-grounding``) shows the effective list with its source and replaces it.
An empty or malformed list is refused (``invalid_high_risk_agent_types``), and so is any other key
(``unknown_setting``): the policy comes from explicit sources only
(``agent/core/context/evidence_grounding``), never from keywords matched over the prompt.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from typing import Any

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.core.context.evidence_grounding import DEFAULT_HIGH_RISK_AGENT_TYPES

from .values import get_system_config_value, set_system_config_value

logger = logging.getLogger(__name__)

EVIDENCE_GROUNDING_CONFIG_KEY = "agent.evidence_grounding_config"
LIVE_EVIDENCE_GROUNDING_KEYS = frozenset({"high_risk_agent_types"})
UNKNOWN_SETTING = "unknown_setting"
INVALID_HIGH_RISK_AGENT_TYPES = "invalid_high_risk_agent_types"


def _normalized_agent_types(value: Any) -> frozenset[str]:
    if not isinstance(value, (list, tuple, set)):
        return DEFAULT_HIGH_RISK_AGENT_TYPES
    cleaned = {str(item).strip().lower() for item in value if str(item).strip()}
    return frozenset(cleaned) if cleaned else DEFAULT_HIGH_RISK_AGENT_TYPES


async def _stored_payload(db: AsyncSession) -> dict[str, Any]:
    raw = await get_system_config_value(db, EVIDENCE_GROUNDING_CONFIG_KEY)
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning(
            "evidence_grounding_config_invalid_json key=%s — using code defaults",
            EVIDENCE_GROUNDING_CONFIG_KEY,
        )
        return {}
    return parsed if isinstance(parsed, dict) else {}


async def get_evidence_grounding_config(db: AsyncSession) -> dict[str, Any]:
    """The effective live setting with its source."""
    payload = await _stored_payload(db)
    stored_types = payload.get("high_risk_agent_types")
    configured = isinstance(stored_types, (list, tuple, set)) and any(str(item).strip() for item in stored_types)
    return {
        "high_risk_agent_types": _normalized_agent_types(stored_types),
        "high_risk_agent_types_source": "configured" if configured else "default",
        "default_high_risk_agent_types": sorted(DEFAULT_HIGH_RISK_AGENT_TYPES),
    }


def _refusal(code: str, message: str, **extra: Any) -> HTTPException:
    return HTTPException(
        status_code=422,
        detail={"code": code, "errors": [{"code": code, "message": message}], **extra},
    )


def refuse_unsupported_evidence_grounding_payload(payload: Mapping[str, Any]) -> None:
    """Refuse a write naming an unknown key or carrying an invalid list (HTTP 422, closed codes)."""
    names = {str(key) for key in payload}
    unknown = sorted(names - LIVE_EVIDENCE_GROUNDING_KEYS)
    if unknown:
        raise _refusal(UNKNOWN_SETTING, "Only high_risk_agent_types can be set.", keys=unknown)
    agent_types = payload.get("high_risk_agent_types")
    if agent_types is None:
        return
    if (
        not isinstance(agent_types, list)
        or not agent_types
        or not all(isinstance(item, str) and item.strip() for item in agent_types)
    ):
        raise _refusal(
            INVALID_HIGH_RISK_AGENT_TYPES,
            "high_risk_agent_types must be a non-empty list of agent type names (null resets to the seed list).",
        )


async def set_evidence_grounding_config(
    db: AsyncSession,
    payload: Mapping[str, Any],
    *,
    updated_by: str | None = None,
) -> dict[str, Any]:
    """The governed write of the live setting; nothing is stored when any key is refused."""
    refuse_unsupported_evidence_grounding_payload(payload)
    live: dict[str, Any] = {}
    agent_types = payload.get("high_risk_agent_types")
    if agent_types is not None:
        live["high_risk_agent_types"] = sorted(_normalized_agent_types(agent_types))
    await set_system_config_value(
        db,
        key=EVIDENCE_GROUNDING_CONFIG_KEY,
        value=json.dumps(live, sort_keys=True) if live else None,
        updated_by=updated_by,
        record_prompt_revision=False,
    )
    return await get_evidence_grounding_config(db)


__all__ = [
    "EVIDENCE_GROUNDING_CONFIG_KEY",
    "get_evidence_grounding_config",
    "refuse_unsupported_evidence_grounding_payload",
    "set_evidence_grounding_config",
]
