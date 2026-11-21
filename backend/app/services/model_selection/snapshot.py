"""Load what the model resolver reads, once per decision: the catalog, the platform order and a Workspace scope."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import ControlPlaneRuntimeTarget, LLMModel, LLMProvider, Project
from ..model_catalog.contract import capabilities_of
from ..model_gateway.data_policy.source import resolve_workspace_data_classification
from ..model_gateway.litellm.policy import MODEL_POLICY_CONFIG_KEY
from ..workspace_composition.assignment_policy import runtime_assignment_mode, selected_runtime_target_ids
from ..workspace_composition.execution_view import (
    get_workspace_default_runtime_target_id,
    get_workspace_execution_view,
    normalize_workspace_execution_view,
)
from .gates import AliasGrant, CatalogModel, WorkspaceScope
from .platform_order import active_config, load_fallback_choice
from .task_models import load_task_models, workspace_task_overrides

ModelRef = tuple[str, str]


@dataclass(frozen=True, slots=True)
class SelectionSnapshot:
    models: dict[str, CatalogModel] = field(default_factory=dict)
    by_ref: dict[ModelRef, str] = field(default_factory=dict)
    by_target: dict[str, str] = field(default_factory=dict)
    order: tuple[str, ...] = ()
    fallback: str = "next"
    task_models: dict[str, str] = field(default_factory=dict)

    def model(self, key: str) -> CatalogModel | None:
        return self.models.get(key)

    def for_ref(self, provider_id: Any, model_id: Any) -> CatalogModel | None:
        key = self.by_ref.get((str(provider_id or ""), str(model_id or "")))
        return self.models.get(key) if key else None

    def for_target(self, target_id: Any) -> CatalogModel | None:
        key = self.by_target.get(str(target_id or "").strip())
        return self.models.get(key) if key else None


async def load_snapshot(db: AsyncSession) -> SelectionSnapshot:
    config = await active_config(db)
    targets = []
    if config is not None:
        targets = list(
            (
                await db.execute(
                    select(ControlPlaneRuntimeTarget)
                    .where(ControlPlaneRuntimeTarget.config_id == config.id)
                    .order_by(ControlPlaneRuntimeTarget.priority, ControlPlaneRuntimeTarget.created_at)
                )
            ).scalars().all()
        )
    target_ids: dict[ModelRef, list[str]] = {}
    target_tags: dict[ModelRef, set[str]] = {}
    for target in targets:
        ref = (target.provider_id, target.model_id)
        target_ids.setdefault(ref, []).append(str(target.id))
        target_tags.setdefault(ref, set()).update(tag.lower() for tag in target.capability_tags)
    joined = select(LLMProvider, LLMModel).join(LLMModel, LLMModel.provider_id == LLMProvider.id)
    rows = (await db.execute(joined)).all()
    models: dict[str, CatalogModel] = {}
    by_ref: dict[ModelRef, str] = {}
    for provider, row in rows:
        if not row.catalog_key:
            continue
        ref = (row.provider_id, row.model_id)
        models[row.catalog_key] = CatalogModel(
            key=row.catalog_key, provider_id=row.provider_id, model_id=row.model_id,
            display_name=row.display_name or row.model_id, provider_name=provider.display_name or provider.name or "",
            driver=str(provider.driver or provider.name or ""), enabled=bool(row.is_active),
            provider_active=bool(provider.is_active), cleared_up_to=row.cleared_up_to,
            capabilities=capabilities_of(row), target_ids=tuple(target_ids.get(ref, ())),
            target_tags=tuple(sorted(target_tags.get(ref, set()))),
        )
        by_ref[ref] = row.catalog_key
    by_target = {
        str(target.id): by_ref[(target.provider_id, target.model_id)]
        for target in targets
        if (target.provider_id, target.model_id) in by_ref
    }
    order: list[str] = []
    for target in targets:
        key = by_target.get(str(target.id))
        if target.is_active and key and key not in order:
            order.append(key)
    return SelectionSnapshot(
        models=models, by_ref=by_ref, by_target=by_target, order=tuple(order),
        fallback=await load_fallback_choice(db), task_models=await load_task_models(db),
    )


def scope_from_view(
    view: dict[str, Any] | None,
    *,
    workspace_id: str = "",
    data_class: str = "",
    task_overrides: dict[str, str] | None = None,
    alias_grant: AliasGrant | None = None,
) -> WorkspaceScope:
    normalized = normalize_workspace_execution_view(view) if view else None
    return WorkspaceScope(
        alias_grant=alias_grant,
        task_overrides=tuple(sorted((task_overrides or {}).items())),
        workspace_id=workspace_id or str((normalized or {}).get("workspace_id") or ""),
        data_class=data_class,
        assignment_mode=runtime_assignment_mode(normalized),
        selected_target_ids=frozenset(selected_runtime_target_ids(normalized)),
        default_target_id=get_workspace_default_runtime_target_id(normalized),
    )


async def load_scope(
    db: AsyncSession,
    *,
    workspace_id: Any,
    view: dict[str, Any] | None = None,
    session_metadata: dict[str, Any] | None = None,
) -> WorkspaceScope:
    """The Workspace's allowlist, ``model_policy`` grant, explicit default and effective data class (the
    server-resolved one)."""
    workspace = str(workspace_id or "").strip()
    if view is None and workspace:
        view = await get_workspace_execution_view(db, workspace_id=workspace, ensure_foundation=False)
    classification = await resolve_workspace_data_classification(
        db, project_id=workspace, session_metadata=session_metadata
    )
    config = (
        (await db.execute(select(Project.config).where(Project.id == workspace))).scalar_one_or_none()
        if workspace
        else None
    )
    return scope_from_view(
        view,
        workspace_id=workspace,
        data_class=classification.classification,
        task_overrides=workspace_task_overrides(config),
        # A Workspace without a ``model_policy`` grants no gateway alias (the admission's deny-by-default).
        alias_grant=(
            AliasGrant.from_policy(config.get(MODEL_POLICY_CONFIG_KEY) if isinstance(config, dict) else None)
            if workspace
            else None
        ),
    )


__all__ = ["SelectionSnapshot", "load_scope", "load_snapshot", "scope_from_view"]
