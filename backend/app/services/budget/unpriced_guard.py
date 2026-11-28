"""Cost caps and unpriced models."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...agent.providers.provider_registry import get_driver_spec
from ...exceptions.tool import BudgetLimitExceededError
from ...models import LLMProvider
from ..model_gateway.cost_contract import GOVERNED_COST_SOURCE_DRIVER
from ..system_config.values import get_system_config_value, set_system_config_value
from .agent_cost_limits import agent_request_cost_limit, agent_session_cost_limit
from .model_pricing import resolve_model_pricing
from .policy_scope import _get_limits_for_period

UNPRICED_MODEL_POLICY_KEY = "agent.unpriced_model_policy"
POLICY_BLOCK = "block"
POLICY_WARN = "warn"
UNPRICED_MODEL_POLICIES = (POLICY_BLOCK, POLICY_WARN)
DEFAULT_UNPRICED_MODEL_POLICY = POLICY_WARN
STATE_NEEDS_CONFIGURATION = "needs_configuration"
REASON_UNPRICED_MODEL = "unpriced_model_under_cost_cap"


class UnpricedModelUnderCostCapError(BudgetLimitExceededError):
    state = STATE_NEEDS_CONFIGURATION
    reason = REASON_UNPRICED_MODEL

    def __init__(self, *, provider_name: str, model_id: str) -> None:
        super().__init__(
            policy_name="Unpriced model", metric_name="cost", projected_value=Decimal("0"), limit_value=Decimal("0"),
            threshold_level="block",
        )
        self.provider_name = provider_name
        self.model_id = model_id
        self.args = (
            f"The model {model_id} ({provider_name}) has no price, so the cost caps in Runtime → Limits & budgets "
            "cannot apply to it. Set its price in Runtime → Model catalog.",
        )

    def __str__(self) -> str:
        return str(self.args[0])


def is_platform_billed_driver(driver: str | None) -> bool:
    spec = get_driver_spec(driver)
    return spec is None or spec.driver != GOVERNED_COST_SOURCE_DRIVER


async def is_platform_billed(db: AsyncSession, provider_name: str) -> bool:
    name = (provider_name or "").strip().lower()
    if not name:
        return False
    row = (await db.execute(
        select(LLMProvider.driver)
        .where(func.lower(LLMProvider.name) == name)
        .order_by(LLMProvider.is_active.desc())
        .limit(1)
    )).first()
    # A name without a configured row has no driver, so it counts as platform billed (the caps apply).
    return is_platform_billed_driver(row.driver) if row is not None else True


async def unpriced_model_policy(db: AsyncSession) -> str:
    value = str(await get_system_config_value(db, UNPRICED_MODEL_POLICY_KEY) or "").strip()
    return value if value in UNPRICED_MODEL_POLICIES else DEFAULT_UNPRICED_MODEL_POLICY


async def set_unpriced_model_policy(db: AsyncSession, value: str) -> str:
    if value not in UNPRICED_MODEL_POLICIES:
        raise ValueError(value)
    await set_system_config_value(
        db, key=UNPRICED_MODEL_POLICY_KEY, value=value,
        description="What a cost cap does with a platform-billed model that has no price: block or warn.",
    )
    return value


async def first_unpriced_runtime(db: AsyncSession, runtimes: list[dict[str, Any]]) -> tuple[str, str] | None:
    for runtime in runtimes or []:
        provider = str(runtime.get("provider_name") or "").strip()
        model = str(runtime.get("model") or "").strip()
        if not provider or not model:
            continue
        driver = str(runtime.get("driver") or "").strip()
        billed = (is_platform_billed_driver(driver) if driver
                  else await is_platform_billed(db, provider))
        if not billed:
            continue
        if not (await resolve_model_pricing(db, provider_name=provider, model_id=model)).priced:
            return provider, model
    return None


async def cost_cap_active(db: AsyncSession, *, project_id: str | None, policies: list[Any]) -> bool:
    if (await agent_request_cost_limit(db, project_id=project_id)).value > 0:
        return True
    if (await agent_session_cost_limit(db, project_id=project_id)).value > 0:
        return True
    return any(Decimal(str(_get_limits_for_period(policy)[2] or 0)) > 0 for policy in policies)


async def enforce_priced_models_under_cap(
    db: AsyncSession, *, runtimes: list[dict[str, Any]], project_id: str | None, policies: list[Any]
) -> None:
    if not await cost_cap_active(db, project_id=project_id, policies=policies):
        return
    unpriced = await first_unpriced_runtime(db, runtimes)
    if unpriced is None or await unpriced_model_policy(db) != POLICY_BLOCK:
        return
    raise UnpricedModelUnderCostCapError(provider_name=unpriced[0], model_id=unpriced[1])


__all__ = [
    "DEFAULT_UNPRICED_MODEL_POLICY",
    "POLICY_BLOCK",
    "POLICY_WARN",
    "REASON_UNPRICED_MODEL",
    "UNPRICED_MODEL_POLICIES",
    "UNPRICED_MODEL_POLICY_KEY",
    "UnpricedModelUnderCostCapError",
    "cost_cap_active",
    "enforce_priced_models_under_cap",
    "first_unpriced_runtime",
    "is_platform_billed",
    "is_platform_billed_driver",
    "set_unpriced_model_policy",
    "unpriced_model_policy",
]
