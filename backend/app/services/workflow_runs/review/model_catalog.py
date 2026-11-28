"""Review runtimes outside the Workspace's runtime chain: an active catalog model of an active provider (Admin ›
Models), never where only selected runtime targets are allowed, never through a provider scoped to another Workspace."""

from __future__ import annotations

from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

CATALOG_PRIORITY = 1000  # after every runtime of the Workspace's own chain


async def _selected_only(db: AsyncSession, project_id: str | None) -> bool:
    from ...workspace_composition import get_workspace_execution_view
    from ...workspace_composition.assignment_policy import runtime_assignment_mode

    if not project_id:
        return False
    view = await get_workspace_execution_view(db, workspace_id=project_id, ensure_foundation=False)
    return runtime_assignment_mode(view) == "selected_only"


async def catalog_runtimes(db: AsyncSession, project_id: str | None, model: str,
                           known_providers: set[str]) -> list[dict[str, Any]]:
    from ....models import LLMModel, LLMProvider
    from ...control_plane.selection_policy import build_runtime_selection_payload
    from ...control_plane_service import build_provider_client_kwargs_async

    if not model or await _selected_only(db, project_id):
        return []
    scope = [LLMProvider.is_global.is_(True), LLMProvider.project_id.is_(None)]
    if project_id:
        scope.append(LLMProvider.project_id == project_id)
    rows = (await db.execute(
        select(LLMModel, LLMProvider).join(LLMProvider, LLMProvider.id == LLMModel.provider_id)
        .where(LLMModel.model_id == model, LLMModel.is_active.is_(True), LLMProvider.is_active.is_(True), or_(*scope))
        .order_by(LLMProvider.name))).all()
    found: list[dict[str, Any]] = []
    for row, provider in rows:
        if provider.id in known_providers:
            continue
        found.append(build_runtime_selection_payload(
            client_kwargs=await build_provider_client_kwargs_async(db, provider), provider=provider, target=None,
            model=row, model_id=model, priority=CATALOG_PRIORITY, use_case_tags=[], max_tokens_per_request=None,
            request_timeout_seconds=None))
        known_providers.add(provider.id)
    return found


__all__ = ["catalog_runtimes"]
