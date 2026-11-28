"""Where a catalog model is used: its platform order position and the Workspaces that may use it."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import ControlPlaneConfig, ControlPlaneRuntimeTarget, Project, WorkspaceCapabilityBinding
from ..model_gateway.litellm.policy import model_alias_access_decision

RUNTIME_BINDING_PREFIX = "runtime-target:"

ModelRef = tuple[str, str]  # (provider id, provider model id)


@dataclass(frozen=True)
class CatalogUsage:
    order_positions: dict[ModelRef, int] = field(default_factory=dict)
    bound_workspaces: dict[ModelRef, set[str]] = field(default_factory=dict)
    workspace_configs: dict[str, dict] = field(default_factory=dict)

    def order_position(self, ref: ModelRef) -> int | None:
        return self.order_positions.get(ref)

    def workspaces(self, ref: ModelRef, *, alias: str | None) -> int:
        used = set(self.bound_workspaces.get(ref, set()))
        if alias:
            used.update(
                workspace_id
                for workspace_id, config in self.workspace_configs.items()
                if model_alias_access_decision(alias, config).allowed
            )
        return len(used)


async def load_usage(db: AsyncSession) -> CatalogUsage:
    targets = (
        await db.execute(
            select(ControlPlaneRuntimeTarget)
            .join(ControlPlaneConfig, ControlPlaneConfig.id == ControlPlaneRuntimeTarget.config_id)
            .where(ControlPlaneConfig.is_active.is_(True))
            .order_by(ControlPlaneRuntimeTarget.priority, ControlPlaneRuntimeTarget.created_at)
        )
    ).scalars().all()
    positions: dict[ModelRef, int] = {}
    position = 0
    for target in targets:
        if not target.is_active:
            continue
        position += 1
        positions.setdefault((target.provider_id, target.model_id), position)
    target_refs = {target.id: (target.provider_id, target.model_id) for target in targets}

    projects = (
        await db.execute(select(Project.id, Project.config).where(Project.is_active.is_(True)))
    ).all()
    configs = {str(project_id): config if isinstance(config, dict) else {} for project_id, config in projects}
    bindings = (
        await db.execute(
            select(WorkspaceCapabilityBinding.workspace_id, WorkspaceCapabilityBinding.binding_key).where(
                WorkspaceCapabilityBinding.capability_kind == "runtime",
                WorkspaceCapabilityBinding.is_enabled.is_(True),
                WorkspaceCapabilityBinding.binding_status != "hidden",
            )
        )
    ).all()
    bound: dict[ModelRef, set[str]] = defaultdict(set)
    for workspace_id, binding_key in bindings:
        if str(workspace_id) not in configs or not str(binding_key).startswith(RUNTIME_BINDING_PREFIX):
            continue
        ref = target_refs.get(str(binding_key)[len(RUNTIME_BINDING_PREFIX):])
        if ref is not None:
            bound[ref].add(str(workspace_id))
    return CatalogUsage(positions, dict(bound), configs)


__all__ = ["CatalogUsage", "load_usage"]
