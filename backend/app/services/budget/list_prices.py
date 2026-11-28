"""Dated list prices of common models (``list_prices.json``), for the first start of an install."""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import LLMModel

_TABLE = Path(__file__).with_name("list_prices.json")


@dataclass(frozen=True)
class ListPrice:
    input: float
    output: float
    cache_read: float | None
    cache_write: float | None
    # The 1-hour prompt-cache write (Anthropic); ``None`` when the table names none.
    cache_write_1h: float | None = None
    # A model priced higher above a prompt size (Haiku 5.5 above 100k, GPT-6 above 272k prompt tokens): that tier.
    long_context: ListPrice | None = None
    above_prompt_tokens: int | None = None


def _price(entry: dict) -> ListPrice:
    long = entry.get("long_context")
    return ListPrice(entry["input"], entry["output"], entry.get("cache_read"), entry.get("cache_write"),
                     entry.get("cache_write_1h"), _price(long) if isinstance(long, dict) else None,
                     int(long["above_prompt_tokens"]) if isinstance(long, dict) else None)


@lru_cache(maxsize=1)
def _table() -> dict[str, ListPrice]:
    models = json.loads(_TABLE.read_text(encoding="utf-8"))["models"]
    return {model_id.lower(): _price(entry) for model_id, entry in models.items()}


def list_price(model_id: str) -> ListPrice | None:
    return _table().get(str(model_id or "").strip().lower())


def call_list_price(model_id: str, *, prompt_tokens: int) -> ListPrice | None:
    price = list_price(model_id)
    if price is not None and price.long_context is not None and prompt_tokens > (price.above_prompt_tokens or 0):
        return price.long_context
    return price


async def apply_list_price(db: AsyncSession, *, provider_id: str, model_id: str) -> bool:
    price = list_price(model_id)
    if price is None:
        return False
    row = (await db.execute(
        select(LLMModel).where(LLMModel.provider_id == provider_id, LLMModel.model_id == model_id)
    )).scalar_one_or_none()
    if row is None or row.pricing_input is not None or row.pricing_output is not None:
        return False
    row.pricing_input, row.pricing_output = price.input, price.output
    row.pricing_cache_read, row.pricing_cache_write = price.cache_read, price.cache_write
    await db.flush()
    return True
