"""``budget`` attention: an active model of a platform-billed provider without a price."""

from __future__ import annotations

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import LLMModel, LLMProvider
from ..budget.unpriced_guard import is_platform_billed_driver
from .links import TARGET_MODEL, fix_link
from .model import KIND_BUDGET, SEVERITY_ATTENTION, CollectContext, Problem, workspace_of

REASON_UNPRICED = "model_unpriced"


async def collect(db: AsyncSession, ctx: CollectContext) -> list[Problem]:
    workspace = func.coalesce(LLMProvider.project_id, "")
    rows = (await db.execute(
        select(LLMModel, LLMProvider)
        .join(LLMProvider, LLMProvider.id == LLMModel.provider_id)
        .where(LLMModel.is_active.is_(True), LLMProvider.is_active.is_(True),
               or_(LLMModel.pricing_input.is_(None), LLMModel.pricing_output.is_(None)), ctx.scope(workspace))
        .order_by(LLMModel.model_id).limit(ctx.limit * 4)
    )).all()
    problems = []
    for model, provider in rows:
        if not is_platform_billed_driver(provider.driver):
            continue
        name = model.display_name or model.model_id
        problems.append(Problem(
            kind=KIND_BUDGET, severity=SEVERITY_ATTENTION, object_type="model", object_id=model.id,
            object_name=name, reason_code=REASON_UNPRICED,
            title=f"Model {name} has no price – costs are not counted.",
            since=getattr(model, "created_at", None), last_seen=ctx.now,
            workspace_id=workspace_of(provider.project_id),
            fix=fix_link(TARGET_MODEL, workspace_id=provider.project_id, object_id=model.id),
        ))
        if len(problems) >= ctx.limit:
            break
    return problems


__all__ = ["REASON_UNPRICED", "collect"]
