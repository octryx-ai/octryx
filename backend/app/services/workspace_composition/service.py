"""Seed helpers for workspace-composition persistence."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import (
    AgentDefinition,
    CapabilityType,
    ControlPlaneRuntimeTarget,
    Project,
    WorkspaceCapabilityBinding,
    WorkspacePolicy,
)
from ..platform_agents.catalog import is_platform_agent_key


def _uuid() -> str:
    return str(uuid.uuid4())


def _agent_type_key(agent_id: str) -> str:
    return f"agent-definition:{agent_id}"


def _runtime_type_key(runtime_target_id: str) -> str:
    return f"runtime-target:{runtime_target_id}"


def _agent_preferences(workspace: Project) -> dict[str, str]:
    config = dict(workspace.config or {}) if isinstance(workspace.config, dict) else {}
    raw = config.get("project_agent_preferences")
    if not isinstance(raw, dict):
        return {}
    preferences: dict[str, str] = {}
    for agent_id, payload in raw.items():
        if not isinstance(payload, dict):
            continue
        status = str(payload.get("status") or "").strip().lower()
        if str(agent_id or "").strip() and status in {"primary", "hidden"}:
            preferences[str(agent_id)] = status
    return preferences


def _binding_status(preference_status: str) -> tuple[str, bool, bool]:
    normalized = str(preference_status or "").strip().lower()
    if normalized == "hidden":
        return "hidden", False, False
    if normalized in {"primary", "default"}:
        return "active", True, True
    return "active", True, False


async def seed_workspace_bundle_foundation(db: AsyncSession, *, workspace_id: str) -> dict[str, Any]:
    workspace = (
        await db.execute(select(Project).where(Project.id == workspace_id))
    ).scalar_one_or_none()
    if workspace is None:
        raise ValueError(f"Workspace not found: {workspace_id}")

    agents = list((await db.execute(
        select(AgentDefinition).where(AgentDefinition.project_id == workspace_id)
        .order_by(AgentDefinition.created_at.asc())
    )).scalars().all())
    runtime_target_ids = sorted({str(agent.runtime_target_id) for agent in agents
                                 if str(agent.runtime_target_id or "").strip() and bool(agent.is_active)})
    runtime_targets = {row.id: row for row in ((await db.execute(
        select(ControlPlaneRuntimeTarget).where(ControlPlaneRuntimeTarget.id.in_(runtime_target_ids))
    )).scalars().all() if runtime_target_ids else [])}

    catalog = await _Catalog.load(db, workspace_id)
    agent_preferences = _agent_preferences(workspace)
    for agent in agents:
        # Platform agents are platform-level, never a Workspace capability binding.
        if agent.is_active and not is_platform_agent_key(agent.builtin_key):
            _seed_agent(catalog, agent, agent_preferences.get(agent.id, ""))
    for runtime_target_id in runtime_target_ids:
        _seed_runtime(catalog, runtime_target_id, runtime_targets.get(runtime_target_id))

    workspace_policy = (
        await db.execute(select(WorkspacePolicy).where(WorkspacePolicy.workspace_id == workspace_id))
    ).scalar_one_or_none()
    if workspace_policy is None:
        workspace_policy = WorkspacePolicy(id=_uuid(), workspace_id=workspace_id)
        db.add(workspace_policy)
    await db.flush()
    return {
        "workspaceId": workspace_id,
        "workspaceName": workspace.name,
        "capabilityTypeCount": len(catalog.types),
        "workspaceBindingCount": len(catalog.bindings),
    }


class _Catalog:
    # The capability types (all) and this Workspace's bindings, created or updated in place.
    def __init__(self, db: AsyncSession, workspace_id: str, types: dict, bindings: dict) -> None:
        self.db, self.workspace_id, self.types, self.bindings = db, workspace_id, types, bindings

    @classmethod
    async def load(cls, db: AsyncSession, workspace_id: str) -> _Catalog:
        types = {(row.kind, row.key): row for row in (await db.execute(select(CapabilityType))).scalars().all()}
        bindings = {row.binding_key: row for row in (await db.execute(
            select(WorkspaceCapabilityBinding).where(WorkspaceCapabilityBinding.workspace_id == workspace_id)
        )).scalars().all()}
        return cls(db, workspace_id, types, bindings)

    def ensure_type(self, *, kind: str, key: str, name: str, description: str, lifecycle_status: str,
                    contract: dict[str, Any]) -> CapabilityType:
        item = self.types.get((kind, key))
        if item is None:
            item = CapabilityType(id=_uuid(), kind=kind, key=key, name=name, description=description,
                                  lifecycle_status=lifecycle_status, contract=contract, is_active=True)
            self.db.add(item)
            self.types[(kind, key)] = item
        else:
            item.name = name
            item.description = description
            item.lifecycle_status = lifecycle_status
            item.contract = contract
            item.is_active = True
        return item

    def ensure_binding(self, *, binding_key: str, preference_status: str, **fields: Any) -> WorkspaceCapabilityBinding:
        # fields: capability_type, capability_kind, display_name, intent_scopes, source_entity_type,
        # source_entity_id, binding_config.
        binding_status, is_enabled, is_default = _binding_status(preference_status)
        values = {**fields, "binding_status": binding_status, "is_enabled": is_enabled, "is_default": is_default,
                  "policy_config": {"preferenceStatus": preference_status or None}}
        binding = self.bindings.get(binding_key)
        if binding is None:
            binding = WorkspaceCapabilityBinding(id=_uuid(), workspace_id=self.workspace_id, binding_key=binding_key,
                                                 **values)
            self.db.add(binding)
            self.bindings[binding_key] = binding
        else:
            for name, value in values.items():
                setattr(binding, name, value)
        return binding


def _seed_agent(catalog: _Catalog, agent: AgentDefinition, preference_status: str) -> None:
    type_key = _agent_type_key(agent.id)
    name = str(agent.name or "").strip() or type_key
    agent_type = str(agent.agent_type or "").strip()
    runtime_target_id = str(agent.runtime_target_id or "").strip() or None
    capability_type = catalog.ensure_type(
        kind="agent", key=type_key, name=name, description=str(agent.description or ""), lifecycle_status="active",
        contract={"sourceEntityType": "agent_definition", "sourceEntityId": agent.id, "agentType": agent_type,
                  "thinkingLevel": str(agent.thinking_level or "").strip(), "runtimeTargetId": runtime_target_id})
    catalog.ensure_binding(
        binding_key=type_key, preference_status=preference_status, capability_type=capability_type,
        capability_kind="agent", display_name=name, intent_scopes=[agent_type] if agent_type else [],
        source_entity_type="agent_definition", source_entity_id=agent.id,
        binding_config={"groupId": str(agent.group_id or "").strip() or None, "runtimeTargetId": runtime_target_id})


def _seed_runtime(catalog: _Catalog, runtime_target_id: str, runtime_target: Any) -> None:
    type_key = _runtime_type_key(runtime_target_id)
    name = (str(runtime_target.model_id).strip() if runtime_target else runtime_target_id) or type_key
    capability_type = catalog.ensure_type(
        kind="runtime", key=type_key, name=name,
        description="Runtime profile of the workspace-linked agent definitions.", lifecycle_status="active",
        contract={"sourceEntityType": "control_plane_runtime_target", "sourceEntityId": runtime_target_id,
                  "modelId": str(runtime_target.model_id).strip() if runtime_target else None,
                  "providerId": str(runtime_target.provider_id).strip() if runtime_target else None})
    catalog.ensure_binding(
        binding_key=type_key, preference_status="", capability_type=capability_type, capability_kind="runtime",
        display_name=name, intent_scopes=[], source_entity_type="control_plane_runtime_target",
        source_entity_id=runtime_target_id, binding_config={})


async def sync_workspace_runtime_catalog_bindings(db: AsyncSession, *, workspace_id: str) -> int:
    active_runtime_targets = list(
        (
            await db.execute(
                select(ControlPlaneRuntimeTarget)
                .where(ControlPlaneRuntimeTarget.is_active.is_(True))
                .order_by(ControlPlaneRuntimeTarget.priority.asc(), ControlPlaneRuntimeTarget.created_at.asc())
            )
        )
        .scalars()
        .all()
    )
    if not active_runtime_targets:
        return 0

    existing_types = {
        (row.kind, row.key): row
        for row in (await db.execute(select(CapabilityType).where(CapabilityType.kind == "runtime"))).scalars().all()
    }
    existing_bindings = {
        row.binding_key: row
        for row in (
            await db.execute(
                select(WorkspaceCapabilityBinding).where(WorkspaceCapabilityBinding.workspace_id == workspace_id)
            )
        )
        .scalars()
        .all()
    }

    created = 0
    for runtime_target in active_runtime_targets:
        runtime_target_id = str(runtime_target.id or "").strip()
        if not runtime_target_id:
            continue
        type_key = _runtime_type_key(runtime_target_id)
        capability_type = existing_types.get(("runtime", type_key))
        if capability_type is None:
            capability_type = CapabilityType(
                id=_uuid(),
                kind="runtime",
                key=type_key,
                name=str(runtime_target.model_id or "").strip() or type_key,
                description="Control-plane runtime target available for explicit project assignment.",
                lifecycle_status="active",
                contract={
                    "sourceEntityType": "control_plane_runtime_target",
                    "sourceEntityId": runtime_target_id,
                    "modelId": str(runtime_target.model_id or "").strip(),
                    "providerId": str(runtime_target.provider_id or "").strip(),
                },
                is_active=True,
            )
            db.add(capability_type)
            existing_types[("runtime", type_key)] = capability_type
        else:
            capability_type.name = str(runtime_target.model_id or "").strip() or type_key
            capability_type.description = "Control-plane runtime target available for explicit project assignment."
            capability_type.lifecycle_status = "active"
            capability_type.contract = {
                "sourceEntityType": "control_plane_runtime_target",
                "sourceEntityId": runtime_target_id,
                "modelId": str(runtime_target.model_id or "").strip(),
                "providerId": str(runtime_target.provider_id or "").strip(),
            }
            capability_type.is_active = True

        if type_key in existing_bindings:
            continue
        db.add(
            WorkspaceCapabilityBinding(
                id=_uuid(),
                workspace_id=workspace_id,
                binding_key=type_key,
                capability_type=capability_type,
                capability_kind="runtime",
                display_name=str(runtime_target.model_id or "").strip() or type_key,
                binding_status="active",
                is_enabled=False,
                is_default=False,
                intent_scopes=list(runtime_target.use_case_tags or []),
                source_entity_type="control_plane_runtime_target",
                source_entity_id=runtime_target_id,
                binding_config={},
                policy_config={"source": "control_plane_runtime_catalog", "defaultEnabled": False},
            )
        )
        created += 1
    if created:
        await db.flush()
    return created


__all__ = [
    "seed_workspace_bundle_foundation",
    "sync_workspace_runtime_catalog_bindings",
]
