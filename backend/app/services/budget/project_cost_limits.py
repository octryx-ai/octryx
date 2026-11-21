"""Project-scoped runtime cost limit overrides.

A Workspace override is a number (``0`` turns the cap off for that Workspace) or absent,
which inherits the platform value. A write changes only the caps it names: a value sets
the override, ``INHERIT_COST_LIMIT`` removes it, and an unnamed cap keeps its state.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import Project

PROJECT_RUNTIME_COST_LIMITS_KEY = "runtime_cost_limits"
SESSION_COST_LIMIT_KEY = "agent_session_cost_limit_usd"
REQUEST_COST_LIMIT_KEY = "agent_request_cost_limit_usd"
COST_LIMIT_KEYS = (SESSION_COST_LIMIT_KEY, REQUEST_COST_LIMIT_KEY)
# The request field that names the caps whose Workspace override is removed (back to inherit).
INHERIT_COST_LIMITS_FIELD = "inherit_cost_limits"
INHERIT_COST_LIMIT = object()


@dataclass(frozen=True)
class ProjectCostLimitOverrides:
    session_cost_limit_usd: Decimal | None
    request_cost_limit_usd: Decimal | None


def _normalize_limit(value: Any) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise HTTPException(status_code=400, detail="Project cost limits must be numeric") from exc
    if parsed < 0 or parsed > Decimal("1000000"):
        raise HTTPException(status_code=400, detail="Project cost limits must be between 0 and 1000000")
    return parsed


def _serialize_limit(value: Decimal | None) -> str | None:
    if value is None:
        return None
    text = format(value.normalize(), "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


async def get_project_cost_limit_overrides(
    db: AsyncSession,
    *,
    project_id: str | None,
) -> ProjectCostLimitOverrides:
    normalized_project_id = str(project_id or "").strip()
    if not normalized_project_id:
        return ProjectCostLimitOverrides(session_cost_limit_usd=None, request_cost_limit_usd=None)
    project = await db.get(Project, normalized_project_id)
    if project is None:
        return ProjectCostLimitOverrides(session_cost_limit_usd=None, request_cost_limit_usd=None)
    config = project.config if isinstance(project.config, dict) else {}
    raw_limits = config.get(PROJECT_RUNTIME_COST_LIMITS_KEY)
    limits = raw_limits if isinstance(raw_limits, dict) else {}
    return ProjectCostLimitOverrides(
        session_cost_limit_usd=_normalize_limit(limits.get(SESSION_COST_LIMIT_KEY)),
        request_cost_limit_usd=_normalize_limit(limits.get(REQUEST_COST_LIMIT_KEY)),
    )


async def set_project_cost_limit_overrides(
    db: AsyncSession,
    *,
    project_id: str,
    updates: dict[str, Any],
) -> ProjectCostLimitOverrides:
    """Apply ``updates`` (cap key -> value or ``INHERIT_COST_LIMIT``); caps not named stay unchanged."""
    normalized_project_id = str(project_id or "").strip()
    if not normalized_project_id:
        raise HTTPException(status_code=400, detail="project_id is required for project cost limit overrides")
    project = await db.get(Project, normalized_project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    config = dict(project.config or {}) if isinstance(project.config, dict) else {}
    cost_limits = dict(config.get(PROJECT_RUNTIME_COST_LIMITS_KEY) or {})
    for key, value in updates.items():
        if key not in COST_LIMIT_KEYS:
            raise HTTPException(status_code=400, detail=f"Unknown project cost limit: {key}")
        if value is INHERIT_COST_LIMIT:
            cost_limits.pop(key, None)
            continue
        limit = _normalize_limit(value)
        if limit is None:
            # An empty override is ambiguous ("no limit" or "inherit"); the caller must say which.
            raise HTTPException(
                status_code=400,
                detail=f"{key}: send a number (0 turns the cap off) or list it in {INHERIT_COST_LIMITS_FIELD}",
            )
        cost_limits[key] = _serialize_limit(limit)

    if cost_limits:
        config[PROJECT_RUNTIME_COST_LIMITS_KEY] = cost_limits
    else:
        config.pop(PROJECT_RUNTIME_COST_LIMITS_KEY, None)
    project.config = config
    await db.flush()
    return ProjectCostLimitOverrides(
        session_cost_limit_usd=_normalize_limit(cost_limits.get(SESSION_COST_LIMIT_KEY)),
        request_cost_limit_usd=_normalize_limit(cost_limits.get(REQUEST_COST_LIMIT_KEY)),
    )


def project_cost_limit_updates(payload: dict[str, Any]) -> dict[str, Any]:
    """The override writes a runtime-settings payload asks for at Workspace scope.

    A cap sent with a value sets it; a cap listed in ``inherit_cost_limits`` goes back to the
    platform value; naming one cap both ways is refused.
    """
    raw_inherit = payload.get(INHERIT_COST_LIMITS_FIELD) or []
    if not isinstance(raw_inherit, list):
        raise HTTPException(status_code=400, detail=f"{INHERIT_COST_LIMITS_FIELD} must be a list of cost limit keys")
    inherit = {str(item) for item in raw_inherit}
    unknown = sorted(inherit - set(COST_LIMIT_KEYS))
    if unknown:
        raise HTTPException(status_code=400, detail=f"Unknown project cost limit: {', '.join(unknown)}")
    conflicting = sorted(key for key in inherit if key in payload)
    if conflicting:
        raise HTTPException(
            status_code=400, detail=f"A cost limit cannot be set and inherited at once: {', '.join(conflicting)}"
        )
    updates: dict[str, Any] = {key: payload[key] for key in COST_LIMIT_KEYS if key in payload}
    updates.update({key: INHERIT_COST_LIMIT for key in inherit})
    return updates
