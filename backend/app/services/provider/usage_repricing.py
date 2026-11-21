"""Re-price past unpriced usage when an admin sets a model's price.

Usage recorded while a platform-billed model had no price was stored with cost 0 (``missing_pricing``). When the
price is saved (Runtime → Model catalog, or the provider's model list), those events of that model are re-priced from
the catalog, so Usage & costs and the caps reflect the real spend. Only Bedrock (decided by the provider's driver)
records per-token usage that the catalog can re-price today; the re-pricing is audited with its counts. No price is
ever set here.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ...agent.providers.provider_registry import get_driver_spec
from ...models import AuditLog, LLMModel, LLMProvider
from .bedrock_pricing import reprice_unpriced_bedrock_usage

BEDROCK_DRIVER = "bedrock_api"
REPRICE_LIMIT = 5000
REPRICED_ACTION = "admin.provider.model.usage_repriced"


async def reprice_after_price_edit(
    db: AsyncSession, *, model: LLMModel, actor_user_id: str | None
) -> dict[str, Any] | None:
    """Re-price this model's unpriced events once it has an input and an output price; ``None`` otherwise."""
    if model.pricing_input is None or model.pricing_output is None:
        return None
    provider = await db.get(LLMProvider, model.provider_id)
    spec = get_driver_spec(provider.driver) if provider is not None else None
    if spec is None or spec.driver != BEDROCK_DRIVER:
        return None
    result = await reprice_unpriced_bedrock_usage(db, model_id=model.model_id, limit=REPRICE_LIMIT)
    if result["events_updated"]:
        db.add(AuditLog(
            user_id=actor_user_id or "system", action=REPRICED_ACTION, resource_type="provider_model",
            resource_id=model.id,
            details={"model_id": model.model_id, "events_updated": result["events_updated"],
                     "cost_total": result["cost_total"]},
        ))
        await db.commit()
    return {"events_updated": result["events_updated"], "cost_total": result["cost_total"]}
