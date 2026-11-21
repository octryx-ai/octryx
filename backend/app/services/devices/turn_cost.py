"""The cost of one device turn, priced by the platform from the turn's own token usage.

Claude Code's ``total_cost_usd`` is the running total of
its whole session, restored on every ``--resume`` (the transcript's ``cost-state`` lines keep one start time across
process restarts); added up per turn, a job's cost would grow with the square of its length. The
device's figure is therefore never added up; it stays on the turn's usage as ``reported_cost_usd``, for
information. The platform prices the turn's ``usage`` (per turn, not cumulative) instead, for every engine and driver:

- per model when the launcher sent ``usage.by_model`` (read from the transcript, subagents included), else the whole
  usage at the model the turn reported;
- at the model catalog's rates (``budget.model_pricing``, the rates every usage event is priced at), else at the
  dated list price (``budget.list_prices``); a model neither knows adds nothing and is named in
  ``usage.unpriced_models`` — never a guess;
- a 1-hour prompt-cache write costs 2x the base input price (Anthropic's rule; the catalog's ``cache_write`` is the
  5-minute rate), a 5-minute write the catalog's cache-write rate.

A turn with no usage, or with only unpriced models, adds no cost.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from sqlalchemy import case, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import LLMModel, LLMProvider
from ..budget.list_prices import list_price
from ..budget.model_pricing import ModelPricing, _rate
from ..budget.prompt_cache_charge import PromptTokenSplit, charge_prompt_split

TRANSCRIPT_SOURCE = "transcript"
COST_SOURCE = "platform_from_usage"
ONE_HOUR_WRITE_FIELD = "cache_creation_1h_input_tokens"
ONE_HOUR_WRITE_INPUT_MULTIPLE = Decimal("2")
_ONE_MILLION = Decimal("1000000")


def _tokens(value: Any) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else 0


async def catalog_pricing(db: AsyncSession, model: str) -> ModelPricing:
    """The catalog row of the model the device named: its own id, else a provider-prefixed id of it
    (``eu.anthropic.claude-…`` on Bedrock, ``anthropic/claude-…``); a global, active, priced row first."""
    exact = LLMModel.model_id == model
    stmt = (
        select(LLMModel.pricing_input, LLMModel.pricing_output, LLMModel.pricing_cache_read,
               LLMModel.pricing_cache_write)
        .join(LLMProvider, LLMModel.provider_id == LLMProvider.id)
        .where(or_(exact, LLMModel.model_id.like(f"%.{model}"), LLMModel.model_id.like(f"%/{model}")),
               or_(LLMModel.pricing_input.is_not(None), LLMModel.pricing_output.is_not(None)))
        .order_by(case((exact, 0), else_=1), LLMProvider.is_global.desc(), LLMModel.is_active.desc())
        .limit(1)
    )
    row = (await db.execute(stmt)).first()
    return ModelPricing(_rate(row[0]), _rate(row[1]), _rate(row[2]), _rate(row[3])) if row else ModelPricing()


async def model_pricing(db: AsyncSession, model: str) -> ModelPricing:
    """The catalog's rates of the model, else its dated list price; an empty ``ModelPricing`` when neither has one."""
    pricing = await catalog_pricing(db, model)
    if pricing.priced:
        return pricing
    listed = list_price(model)
    if listed is None:
        return ModelPricing()
    return ModelPricing(_rate(listed.input), _rate(listed.output), _rate(listed.cache_read), _rate(listed.cache_write))


def one_hour_writes(usage: dict[str, Any]) -> int:
    """The 1-hour cache writes of a usage row: the launcher's flat field, else Claude's ``cache_creation`` detail."""
    flat = _tokens(usage.get(ONE_HOUR_WRITE_FIELD))
    if flat:
        return flat
    detail = usage.get("cache_creation")
    return _tokens(detail.get("ephemeral_1h_input_tokens")) if isinstance(detail, dict) else 0


def charge(pricing: ModelPricing, usage: dict[str, Any]) -> Decimal:
    """Unrounded USD of one model's usage (Anthropic keys: input without the cached part, cache tokens on top)."""
    writes = _tokens(usage.get("cache_creation_input_tokens"))
    one_hour = min(one_hour_writes(usage), writes) if pricing.has_cache_rates and pricing.input is not None else 0
    split = PromptTokenSplit(uncached_input_tokens=_tokens(usage.get("input_tokens")),
                             cache_read_tokens=_tokens(usage.get("cache_read_input_tokens")),
                             cache_write_tokens=writes - one_hour)
    cost, _status = charge_prompt_split(pricing, split=split, prompt_tokens=split.uncached_input_tokens,
                                        completion_tokens=_tokens(usage.get("output_tokens")))
    if one_hour:
        cost += Decimal(one_hour) * pricing.input * ONE_HOUR_WRITE_INPUT_MULTIPLE / _ONE_MILLION
    return cost


async def price_turn(db: AsyncSession, body: dict[str, Any], *, model: str) -> dict[str, Any]:
    """``body`` with the platform's ``cost_usd`` of the turn (``None`` when nothing could be priced); the figure the
    device sent as ``cost_usd`` is kept as ``usage.reported_cost_usd`` (top-level ``reported_cost_usd`` when the body
    carries no usage). ``model`` prices a usage that has no ``by_model``."""
    reported = body.get("cost_usd")
    usage = body.get("usage")
    if not isinstance(usage, dict):
        return {**body, "cost_usd": None, "reported_cost_usd": reported}
    by_model = usage.get("by_model")
    rows = by_model if isinstance(by_model, dict) else ({model: usage} if model else {})
    total, priced, unpriced = Decimal("0"), False, []
    for name, row in rows.items():
        if not isinstance(name, str) or not isinstance(row, dict):
            continue
        pricing = await model_pricing(db, name[:200])
        if not pricing.priced:
            unpriced.append(name[:200])
            continue
        total += charge(pricing, row)
        priced = True
    cost_usd = float(total.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)) if priced else None
    return {**body, "cost_usd": cost_usd,
            "usage": {**usage, "cost_source": COST_SOURCE, "unpriced_models": sorted(unpriced),
                      "reported_cost_usd": reported}}


__all__ = ["COST_SOURCE", "ONE_HOUR_WRITE_FIELD", "TRANSCRIPT_SOURCE", "catalog_pricing", "charge", "model_pricing",
           "one_hour_writes", "price_turn"]
