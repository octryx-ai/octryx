"""Persisted catalog pricing of one model row, and the per-token-class charge it implies.

The rates are the ones model-catalog sync (or an operator) stored on ``llm_models``
in USD per million tokens. The prompt-cache pair is optional; a governed
``catalog_pricing`` sync (``services/model_gateway/cost_contract``) writes it, or an
admin while no cost source owns the price (``services/admin/provider/model_price_edit``).

Cache token convention: ``cache_read_tokens`` / ``cache_creation_tokens`` passed
here are *additional* to the prompt tokens — the Anthropic convention the gateway
inbound route and ``session_ingest`` store on a ``UsageEvent`` (``tokens_in`` is the
uncached input). Bedrock Converse payloads fold cache tokens into the prompt count;
``prompt_cache_charge`` splits them before they reach ``charge``.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from ...models import LLMModel, LLMProvider

_ONE_MILLION = Decimal("1000000")
_ZERO = Decimal("0")


def _rate(value: Any) -> Decimal | None:
    return None if value is None else Decimal(str(value))


@dataclass(frozen=True, slots=True)
class ModelPricing:
    input: Decimal | None = None
    output: Decimal | None = None
    cache_read: Decimal | None = None
    cache_write: Decimal | None = None

    @property
    def priced(self) -> bool:
        return self.input is not None or self.output is not None

    @property
    def has_cache_rates(self) -> bool:
        return self.cache_read is not None and self.cache_write is not None

    def charge(
        self,
        *,
        prompt_tokens: int,
        completion_tokens: int,
        cache_read_tokens: int = 0,
        cache_creation_tokens: int = 0,
    ) -> Decimal:
        """Unrounded USD charge. Cache tokens count only when the row has its own cache rates."""

        total = Decimal(prompt_tokens) * (self.input or _ZERO) + Decimal(completion_tokens) * (self.output or _ZERO)
        if self.has_cache_rates:
            total += Decimal(max(0, cache_read_tokens)) * self.cache_read
            total += Decimal(max(0, cache_creation_tokens)) * self.cache_write
        return total / _ONE_MILLION


async def resolve_model_pricing(db: AsyncSession, *, provider_name: str, model_id: str) -> ModelPricing:
    """The pricing of the best-matching model row; an empty ``ModelPricing`` when none exists."""

    provider_alias = aliased(LLMProvider)
    stmt = (
        select(
            LLMModel.pricing_input,
            LLMModel.pricing_output,
            LLMModel.pricing_cache_read,
            LLMModel.pricing_cache_write,
        )
        .join(provider_alias, LLMModel.provider_id == provider_alias.id)
        .where(provider_alias.name == provider_name, LLMModel.model_id == model_id)
        .order_by(provider_alias.is_global.desc(), LLMModel.is_active.desc())
        .limit(1)
    )
    row = (await db.execute(stmt)).first()
    if not row:
        return ModelPricing()
    return ModelPricing(_rate(row[0]), _rate(row[1]), _rate(row[2]), _rate(row[3]))


__all__ = ["ModelPricing", "resolve_model_pricing"]
