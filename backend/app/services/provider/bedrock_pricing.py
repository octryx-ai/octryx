"""AWS Bedrock pricing sync and re-pricing of unpriced Bedrock usage from the model catalog."""

from __future__ import annotations

import asyncio
import json
import re
import urllib.request
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import LLMModel, LLMProvider, UsageEvent
from ...services.budget.model_pricing import resolve_model_pricing
from ...services.budget.prompt_cache_charge import PromptTokenSplit, charge_prompt_split

BEDROCK_PRICING_OFFER_URL = "https://pricing.us-east-1.amazonaws.com/offers/v1.0/aws/AmazonBedrock/current/index.json"

_ONE_MILLION = Decimal("1000000")
_ONE_THOUSAND = Decimal("1000")
_ZERO = Decimal("0")
_MODEL_VERSION_RE = re.compile(r"^(?:20\d{6}|v\d+)$", re.IGNORECASE)
_NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")
_STANDARD_INPUT_TOKEN_TYPES = {"input tokens"}
_STANDARD_OUTPUT_TOKEN_TYPES = {"output tokens"}


@dataclass(frozen=True)
class BedrockPricingEntry:
    region_code: str
    model_key: str
    input_per_million: Decimal | None = None
    output_per_million: Decimal | None = None


def _normalize_key(value: str) -> str:
    return _NON_ALNUM_RE.sub("", value.strip().lower())


def _model_match_keys(model_id: str) -> set[str]:
    raw = str(model_id or "").strip()
    if not raw:
        return set()
    without_revision = raw.split(":", 1)[0]
    without_provider = without_revision.split(".", 1)[-1]
    parts = [part for part in without_provider.split("-") if part and not _MODEL_VERSION_RE.match(part)]
    keys = {_normalize_key(raw), _normalize_key(without_revision), _normalize_key(without_provider)}
    if parts:
        compact = "".join(parts)
        keys.add(_normalize_key(compact))
        if compact.startswith("nova2"):
            keys.add(_normalize_key(compact.replace("nova2", "nova20", 1)))
        if len(parts) >= 3 and parts[0] == "claude":
            family_parts = parts[1:]
            keys.add(_normalize_key("claude" + "".join(family_parts)))
            if len(family_parts) >= 2 and family_parts[0] == "sonnet" and family_parts[1].isdigit():
                keys.add(_normalize_key("claude" + family_parts[1] + "sonnet" + "".join(family_parts[2:])))
    return {key for key in keys if key}


def _price_per_million(price_per_unit: str, unit: str) -> Decimal | None:
    try:
        price = Decimal(str(price_per_unit))
    except Exception:
        return None
    normalized_unit = str(unit or "").strip().lower()
    if "1k" in normalized_unit or "1000" in normalized_unit:
        return (price * _ONE_THOUSAND).quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)
    if "1m" in normalized_unit or "million" in normalized_unit:
        return price.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)
    if "token" in normalized_unit:
        return (price * _ONE_MILLION).quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)
    return None


def _extract_term_price(terms: dict[str, Any], sku: str) -> tuple[Decimal | None, str]:
    on_demand_terms = terms.get("OnDemand") or {}
    sku_terms = on_demand_terms.get(sku) or {}
    for term in sku_terms.values():
        for dimension in (term.get("priceDimensions") or {}).values():
            usd = (dimension.get("pricePerUnit") or {}).get("USD")
            price = _price_per_million(str(usd or ""), str(dimension.get("unit") or ""))
            if price is not None:
                return price, str(dimension.get("description") or "")
    return None, ""


def build_bedrock_pricing_index(offer_payload: dict[str, Any]) -> dict[tuple[str, str], BedrockPricingEntry]:
    """Parse the AWS Bedrock offer file into model-keyed token prices."""

    products = offer_payload.get("products") or {}
    terms = offer_payload.get("terms") or {}
    indexed: dict[tuple[str, str], BedrockPricingEntry] = {}
    for sku, product in products.items():
        attributes = product.get("attributes") or {}
        feature = str(attributes.get("feature") or "").lower()
        inference_type = str(attributes.get("inferenceType") or "").lower()
        model_name = str(attributes.get("model") or "").strip()
        region_code = str(attributes.get("regionCode") or "").strip()
        if (
            "on-demand" not in feature
            or inference_type not in _STANDARD_INPUT_TOKEN_TYPES | _STANDARD_OUTPUT_TOKEN_TYPES
            or not model_name
            or not region_code
        ):
            continue
        price, _description = _extract_term_price(terms, str(sku))
        if price is None:
            continue
        model_key = _normalize_key(model_name)
        index_key = (region_code, model_key)
        current = indexed.get(index_key) or BedrockPricingEntry(region_code=region_code, model_key=model_key)
        if inference_type in _STANDARD_INPUT_TOKEN_TYPES:
            current = BedrockPricingEntry(
                region_code=current.region_code,
                model_key=current.model_key,
                input_per_million=price,
                output_per_million=current.output_per_million,
            )
        elif inference_type in _STANDARD_OUTPUT_TOKEN_TYPES:
            current = BedrockPricingEntry(
                region_code=current.region_code,
                model_key=current.model_key,
                input_per_million=current.input_per_million,
                output_per_million=price,
            )
        indexed[index_key] = current
    return indexed


async def fetch_bedrock_pricing_offer() -> dict[str, Any]:
    def _fetch() -> dict[str, Any]:
        with urllib.request.urlopen(BEDROCK_PRICING_OFFER_URL, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))

    return await asyncio.to_thread(_fetch)


def _resolve_index_entry(
    index: dict[tuple[str, str], BedrockPricingEntry],
    *,
    model_id: str,
    region_code: str | None,
) -> BedrockPricingEntry | None:
    keys = _model_match_keys(model_id)
    if not keys:
        return None
    if region_code:
        for key in keys:
            entry = index.get((region_code, key))
            if entry:
                return entry
        return None
    matches = [entry for (entry_region, key), entry in index.items() if entry_region and key in keys]
    unique_prices = {
        (entry.input_per_million, entry.output_per_million)
        for entry in matches
        if entry.input_per_million is not None or entry.output_per_million is not None
    }
    if len(unique_prices) == 1 and matches:
        return matches[0]
    return None


async def sync_bedrock_model_pricing(
    db: AsyncSession,
    *,
    offer_payload: dict[str, Any] | None = None,
    fetch_offer_func=fetch_bedrock_pricing_offer,
) -> dict[str, Any]:
    payload = offer_payload or await fetch_offer_func()
    index = build_bedrock_pricing_index(payload)
    rows = (
        (
            await db.execute(
                select(LLMModel, LLMProvider)
                .join(LLMProvider, LLMModel.provider_id == LLMProvider.id)
                .where(LLMProvider.driver == "bedrock_api")
            )
        )
        .all()
    )
    updated = 0
    skipped_without_price = 0
    for model, provider in rows:
        entry = _resolve_index_entry(index, model_id=model.model_id, region_code=provider.aws_region)
        if not entry:
            skipped_without_price += 1
            continue
        changed = False
        if entry.input_per_million is not None and model.pricing_input != float(entry.input_per_million):
            model.pricing_input = float(entry.input_per_million)
            changed = True
        if entry.output_per_million is not None and model.pricing_output != float(entry.output_per_million):
            model.pricing_output = float(entry.output_per_million)
            changed = True
        if changed:
            updated += 1
    await db.commit()
    return {
        "status": "synced",
        "pricing_rows": len(index),
        "models_seen": len(rows),
        "models_updated": updated,
        "models_without_official_price": skipped_without_price,
        "publication_date": payload.get("publicationDate"),
    }


async def _catalog_event_charge(db: AsyncSession, *, event: UsageEvent, model_id: str) -> tuple[Decimal, str]:
    """Price one recorded Bedrock event from the catalog, cache columns included.

    The cache pair is the catalog's (``llm_models.pricing_cache_read/_write``); this
    module holds no price table of its own.
    """

    pricing = await resolve_model_pricing(db, provider_name="bedrock", model_id=model_id)
    if not pricing.priced:
        return _ZERO, "missing_pricing"
    split = PromptTokenSplit(
        uncached_input_tokens=int(event.tokens_in or 0),
        cache_read_tokens=int(event.cache_read_tokens or 0),
        cache_write_tokens=int(event.cache_creation_tokens or 0),
        converse=True,
    )
    cost, cost_status = charge_prompt_split(
        pricing,
        split=split,
        prompt_tokens=split.uncached_input_tokens + split.cache_tokens,
        completion_tokens=int(event.tokens_out or 0),
    )
    return cost.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP), cost_status


async def reprice_unpriced_bedrock_usage(db: AsyncSession, *, model_id: str, limit: int = 1000) -> dict[str, Any]:
    """Price this model's recorded Bedrock events that carry no cost yet, from the catalog; commits.

    Returns ``events_updated`` and ``cost_total`` (a decimal string).
    """
    bounded_limit = max(1, min(int(limit or 1000), 5000))
    events = (
        await db.execute(
            select(UsageEvent)
            .where(
                UsageEvent.provider == "bedrock",
                UsageEvent.model == model_id,
                or_(UsageEvent.cost.is_(None), UsageEvent.cost == 0),
                or_(UsageEvent.tokens_in > 0, UsageEvent.tokens_out > 0),
            )
            .order_by(UsageEvent.created_at.asc(), UsageEvent.id.asc())
            .limit(bounded_limit)
        )
    ).scalars().all()
    updated = 0
    total_cost = _ZERO
    for event in events:
        cost, cost_status = await _catalog_event_charge(db, event=event, model_id=model_id)
        if cost <= 0:
            continue
        total_cost += cost
        updated += 1
        event.cost = cost
        event.cost_status = cost_status
    await db.commit()
    return {
        "events_updated": updated,
        "cost_total": str(total_cost.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)),
    }


__all__ = [
    "BEDROCK_PRICING_OFFER_URL",
    "build_bedrock_pricing_index",
    "reprice_unpriced_bedrock_usage",
    "sync_bedrock_model_pricing",
]
