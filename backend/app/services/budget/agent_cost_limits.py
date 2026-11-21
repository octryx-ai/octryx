"""The default agent session and request cost limits, and where each value comes from.

Precedence: the Workspace override (``runtime_cost_limits``), else the
admin ``system_config`` value, else the environment, else the code default. ``0`` turns a limit off. The
source is ``workspace``, ``global`` (system config or environment) or ``default``; an unreadable instance
value falls back to the code default and reports ``default``.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from ..system_config.constants import (
    AGENT_REQUEST_COST_LIMIT_USD_KEY,
    AGENT_SESSION_COST_LIMIT_USD_KEY,
    DEFAULT_AGENT_REQUEST_COST_LIMIT_USD,
    DEFAULT_AGENT_SESSION_COST_LIMIT_USD,
)
from ..system_config.values import get_system_config_value
from .project_cost_limits import get_project_cost_limit_overrides

SOURCE_WORKSPACE = "workspace"
SOURCE_GLOBAL = "global"
SOURCE_DEFAULT = "default"

SESSION_COST_LIMIT_ENV = "OCTRYX_AGENT_SESSION_COST_LIMIT_USD"
REQUEST_COST_LIMIT_ENV = "OCTRYX_AGENT_REQUEST_COST_LIMIT_USD"
_ZERO = Decimal("0")
_DEFAULT_SESSION = Decimal(str(DEFAULT_AGENT_SESSION_COST_LIMIT_USD))
_DEFAULT_REQUEST = Decimal(str(DEFAULT_AGENT_REQUEST_COST_LIMIT_USD))


@dataclass(frozen=True, slots=True)
class CostLimit:
    value: Decimal
    source: str


def _parsed(raw_value: object) -> Decimal | None:
    try:
        return max(_ZERO, Decimal(str(raw_value)))
    except (ArithmeticError, ValueError):
        return None


async def _instance_limit(db: AsyncSession, *, key: str, env_name: str, default: Decimal) -> CostLimit:
    raw_value = await get_system_config_value(db, key)
    if raw_value not in (None, ""):
        parsed = _parsed(raw_value)
        return CostLimit(parsed, SOURCE_GLOBAL) if parsed is not None else CostLimit(default, SOURCE_DEFAULT)
    env_value = os.getenv(env_name)
    if env_value in (None, ""):
        return CostLimit(default, SOURCE_DEFAULT)
    parsed = _parsed(env_value)
    return CostLimit(parsed, SOURCE_GLOBAL) if parsed is not None else CostLimit(default, SOURCE_DEFAULT)


async def agent_session_cost_limit(db: AsyncSession, *, project_id: str | None) -> CostLimit:
    """The per-session cost ceiling in USD and its source."""
    override = (await get_project_cost_limit_overrides(db, project_id=project_id)).session_cost_limit_usd
    if override is not None:
        return CostLimit(override, SOURCE_WORKSPACE)
    return await _instance_limit(
        db, key=AGENT_SESSION_COST_LIMIT_USD_KEY, env_name=SESSION_COST_LIMIT_ENV, default=_DEFAULT_SESSION
    )


async def agent_request_cost_limit(db: AsyncSession, *, project_id: str | None) -> CostLimit:
    """The per-request cost ceiling in USD and its source."""
    override = (await get_project_cost_limit_overrides(db, project_id=project_id)).request_cost_limit_usd
    if override is not None:
        return CostLimit(override, SOURCE_WORKSPACE)
    return await _instance_limit(
        db, key=AGENT_REQUEST_COST_LIMIT_USD_KEY, env_name=REQUEST_COST_LIMIT_ENV, default=_DEFAULT_REQUEST
    )


async def platform_cost_limits(db: AsyncSession) -> tuple[CostLimit, CostLimit]:
    """The platform session and request caps a Workspace inherits (no Workspace override applied)."""
    session = await _instance_limit(
        db, key=AGENT_SESSION_COST_LIMIT_USD_KEY, env_name=SESSION_COST_LIMIT_ENV, default=_DEFAULT_SESSION
    )
    request = await _instance_limit(
        db, key=AGENT_REQUEST_COST_LIMIT_USD_KEY, env_name=REQUEST_COST_LIMIT_ENV, default=_DEFAULT_REQUEST
    )
    return session, request


__all__ = [
    "platform_cost_limits",
    "SOURCE_DEFAULT",
    "SOURCE_GLOBAL",
    "SOURCE_WORKSPACE",
    "CostLimit",
    "agent_request_cost_limit",
    "agent_session_cost_limit",
]
