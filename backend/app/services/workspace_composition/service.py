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
    """The Workspace's agent preference statuses (``project_agent_preferences``), by agent id."""
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

    agents = list(
        (
            await db.execute(
                select(AgentDefinition)
                .where(AgentDefinition.project_id == workspace_id)
                .order_by(AgentDefinition.created_at.asc())
            )
        )
        .scalars()
        .all()
    )
    runtime_target_ids = sorted(
        {
            str(agent.runtime_target_id)
            for agent in agents
            if str(agent.runtime_target_id or "").strip() and bool(agent.is_active)
        }
    )
    runtime_targets = {
        row.id: row
        for row in (
            (
                await db.execute(
                    select(ControlPlaneRuntimeTarget).where(ControlPlaneRuntimeTarget.id.in_(runtime_target_ids))
                )
            )
            .scalars()
            .all()
            if runtime_target_ids
            else []
        )
    }

    agent_preferences = _agent_preferences(workspace)

    existing_types = {
        (row.kind, row.key): row
        for row in (
            await db.execute(select(CapabilityType))
        ).scalars().all()
    }
    existing_bindings = {
        row.binding_key: row
        for row in (
            await db.execute(
                select(WorkspaceCapabilityBinding).where(WorkspaceCapabilityBinding.workspace_id == workspace_id)
            )
        ).scalars().all()
    }

    def ensure_type(
        *,
        kind: str,
        key: str,
        name: str,
        description: str,
        lifecycle_status: str,
        contract: dict[str, Any],
    ) -> CapabilityType:
        item = existing_types.get((kind, key))
        if item is None:
            item = CapabilityType(
                id=_uuid(),
                kind=kind,
                key=key,
                name=name,
                description=description,
                lifecycle_status=lifecycle_status,
                contract=contract,
                is_active=True,
            )
            db.add(item)
            existing_types[(kind, key)] = item
        else:
            item.name = name
            item.description = description
            item.lifecycle_status = lifecycle_status
            item.contract = contract
            item.is_active = True
        return item

    def ensure_binding(
        *,
        binding_key: str,
        capability_type: CapabilityType,
        capability_kind: str,
        display_name: str,
        preference_status: str,
        intent_scopes: list[str],
        source_entity_type: str,
        source_entity_id: str,
        binding_config: dict[str, Any],
    ) -> WorkspaceCapabilityBinding:
        binding = existing_bindings.get(binding_key)
        binding_status, is_enabled, is_default = _binding_status(preference_status)
        if binding is None:
            binding = WorkspaceCapabilityBinding(
                id=_uuid(),
                workspace_id=workspace_id,
                binding_key=binding_key,
                capability_type=capability_type,
                capability_kind=capability_kind,
                display_name=display_name,
                binding_status=binding_status,
                is_enabled=is_enabled,
                is_default=is_default,
                intent_scopes=intent_scopes,
                source_entity_type=source_entity_type,
                source_entity_id=source_entity_id,
                binding_config=binding_config,
                policy_config={"preferenceStatus": preference_status or None},
            )
            db.add(binding)
            existing_bindings[binding_key] = binding
        else:
            binding.capability_type = capability_type
            binding.capability_kind = capability_kind
            binding.display_name = display_name
            binding.binding_status = binding_status
            binding.is_enabled = is_enabled
            binding.is_default = is_default
            binding.intent_scopes = intent_scopes
            binding.source_entity_type = source_entity_type
            binding.source_entity_id = source_entity_id
            binding.binding_config = binding_config
            binding.policy_config = {"preferenceStatus": preference_status or None}
        return binding

    for agent in agents:
        # Platform agents are platform-level, never a Workspace capability binding.
        if not agent.is_active or is_platform_agent_key(agent.builtin_key):
            continue
        type_key = _agent_type_key(agent.id)
        capability_type = ensure_type(
            kind="agent",
            key=type_key,
            name=str(agent.name or "").strip() or type_key,
            description=str(agent.description or ""),
            lifecycle_status="active",
            contract={
                "sourceEntityType": "agent_definition",
                "sourceEntityId": agent.id,
                "agentType": str(agent.agent_type or "").strip(),
                "thinkingLevel": str(agent.thinking_level or "").strip(),
                "runtimeTargetId": str(agent.runtime_target_id or "").strip() or None,
            },
        )
        pref_status = agent_preferences.get(agent.id, "")
        ensure_binding(
            binding_key=type_key,
            capability_type=capability_type,
            capability_kind="agent",
            display_name=str(agent.name or "").strip() or type_key,
            preference_status=pref_status,
            intent_scopes=[str(agent.agent_type or "").strip()] if str(agent.agent_type or "").strip() else [],
            source_entity_type="agent_definition",
            source_entity_id=agent.id,
            binding_config={
                "groupId": str(agent.group_id or "").strip() or None,
                "runtimeTargetId": str(agent.runtime_target_id or "").strip() or None,
            },
        )

    for runtime_target_id in runtime_target_ids:
        runtime_target = runtime_targets.get(runtime_target_id)
        type_key = _runtime_type_key(runtime_target_id)
        capability_type = ensure_type(
            kind="runtime",
            key=type_key,
            name=(str(runtime_target.model_id).strip() if runtime_target else runtime_target_id) or type_key,
            description="Runtime profile of the workspace-linked agent definitions.",
            lifecycle_status="active",
            contract={
                "sourceEntityType": "control_plane_runtime_target",
                "sourceEntityId": runtime_target_id,
                "modelId": str(runtime_target.model_id).strip() if runtime_target else None,
                "providerId": str(runtime_target.provider_id).strip() if runtime_target else None,
            },
        )
        ensure_binding(
            binding_key=type_key,
            capability_type=capability_type,
            capability_kind="runtime",
            display_name=(str(runtime_target.model_id).strip() if runtime_target else runtime_target_id) or type_key,
            preference_status="",
            intent_scopes=[],
            source_entity_type="control_plane_runtime_target",
            source_entity_id=runtime_target_id,
            binding_config={},
        )

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
        "capabilityTypeCount": len(existing_types),
        "workspaceBindingCount": len(existing_bindings),
    }


async def sync_workspace_runtime_catalog_bindings(db: AsyncSession, *, workspace_id: str) -> int:
    """Expose active control-plane runtimes as project-selectable bindings.

    Runtime bindings created from the global catalog start disabled. That keeps
    existing projects on their current automatic runtime behavior until an admin
    deliberately enables one or switches the project to ``selected_only``.
    """

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
