"""Control plane and agent definition helpers."""

from fastapi import Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.services.control_plane.service_helpers import get_copilot_auth_session_info, provider_secret_scope

from ...agent.providers import list_supported_driver_names
from ...models import (
    AgentDefinition,
    LLMModel,
    LLMProvider,
    Project,
    SavedPythonScript,
    User,
)
from ...models.runtime.provider_oauth_config import oauth_metadata_from_provider
from ...services.agent_visibility import visible_agent_clause
from ...services.control_plane_service import (
    get_or_create_control_plane_config,
    get_provider_auth_mode,
    get_runtime_targets,
)
from ...services.provider_runtime_config import resolve_provider_default_model
from ...services.script import list_saved_scripts
from ...services.secret import get_secret_value, secret_ref_label
from ...services.tool_config import (
    TOOL_CONFIG_PRESETS,
    build_tool_config_forms,
    list_tool_configs,
)
from .auth import COPILOT_DEVICE_FLOW_STATE

__all__ = [
    "_build_control_plane_context",
    "_build_tools_context",
    "_list_agent_definitions",
]


def _tool_registry():
    from ...tools.registry import TOOL_REGISTRY

    return TOOL_REGISTRY


async def _load_global_providers(db: AsyncSession) -> list[LLMProvider]:
    """The global providers, each with its ``model_count`` attached for the provider list."""
    result = await db.execute(
        select(LLMProvider)
        .where(LLMProvider.is_global)
        .options(selectinload(LLMProvider.oauth_config))
        .order_by(LLMProvider.display_name, LLMProvider.name)
    )
    providers = result.scalars().all()
    provider_ids = [provider.id for provider in providers]
    model_counts = {}
    if provider_ids:
        result = await db.execute(
            select(LLMModel.provider_id, func.count(LLMModel.id))
            .where(LLMModel.provider_id.in_(provider_ids))
            .group_by(LLMModel.provider_id)
        )
        model_counts = {provider_id: count for provider_id, count in result.all()}
    for provider in providers:
        setattr(provider, "model_count", model_counts.get(provider.id, 0))
    return providers


async def _editing_provider_has_key(db: AsyncSession, editing_provider: LLMProvider | None) -> bool:
    if not editing_provider:
        return False
    if getattr(editing_provider, "api_key_secret_ref", None):
        return bool(await get_secret_value(db, secret_id=editing_provider.api_key_secret_ref))
    tool_name, field_name = provider_secret_scope(editing_provider)
    return bool(await get_secret_value(db, tool_name=tool_name, field_name=field_name, project_id=None))


def _pending_copilot_flow(request: Request, editing_provider: LLMProvider | None) -> dict | None:
    pending_flow_id = request.query_params.get("copilot_flow_id")
    if not pending_flow_id:
        return None
    flow = COPILOT_DEVICE_FLOW_STATE.get(pending_flow_id)
    if flow and (not editing_provider or flow.get("provider_id") == editing_provider.id):
        return {
            "id": pending_flow_id,
            "verification_uri": flow.get("verification_uri"),
            "user_code": flow.get("user_code"),
            "status": flow.get("status", "pending"),
            "error": flow.get("error", ""),
        }
    return None


async def _active_provider_models(db: AsyncSession, editing_provider: LLMProvider | None) -> list[LLMModel]:
    if not editing_provider:
        return []
    result = await db.execute(
        select(LLMModel)
        .where(LLMModel.provider_id == editing_provider.id)
        .where(LLMModel.is_active)
        .order_by(LLMModel.display_name, LLMModel.model_id)
    )
    return result.scalars().all()


async def _runtime_target_rows(db: AsyncSession, config, active_provider: LLMProvider | None) -> list[dict]:
    runtime_target_rows = []
    for target in await get_runtime_targets(db, config):
        provider = await db.get(LLMProvider, target.provider_id)
        runtime_target_rows.append(
            {
                "id": target.id,
                "provider_id": target.provider_id,
                "provider_name": provider.name if provider else "unknown",
                "provider_display_name": provider.display_name if provider else "Unknown Provider",
                "model_id": target.model_id,
                "priority": target.priority,
                "is_active": target.is_active,
                "is_primary": bool(
                    active_provider and active_provider.id == target.provider_id and config.model_id == target.model_id
                ),
            }
        )
    return runtime_target_rows


def _runtime_provider_options(providers: list[LLMProvider], config) -> list[dict]:
    return [
        {
            "id": provider.id,
            "label": provider.display_name or provider.name,
            "provider_type": provider.name,
            "default_model_id": resolve_provider_default_model(
                provider,
                fallback_model_id=config.model_id or "",
            )
            or "",
        }
        for provider in providers
        if provider.is_active
    ]


def _selected_model_id(editing_provider: LLMProvider | None, config) -> str:
    if not editing_provider:
        return config.model_id or ""
    return resolve_provider_default_model(editing_provider, config=config, fallback_model_id=config.model_id or "")


async def _build_control_plane_context(
    request: Request,
    db: AsyncSession,
    *,
    edit_provider_id: str | None = None,
    new_provider: bool = False,
    test_prompt: str = "",
    test_response: str | None = None,
    test_error: str | None = None,
) -> dict:
    config = await get_or_create_control_plane_config(db)
    providers = await _load_global_providers(db)
    _oauth_config_load = {"options": [selectinload(LLMProvider.oauth_config)]}
    active_provider = (
        await db.get(LLMProvider, config.provider_id, **_oauth_config_load) if config.provider_id else None
    )
    editing_provider = None
    if edit_provider_id and not new_provider:
        editing_provider = await db.get(LLMProvider, edit_provider_id, **_oauth_config_load)
    if not editing_provider and not new_provider:
        editing_provider = active_provider

    editing_provider_has_key = await _editing_provider_has_key(db, editing_provider)
    models = await _active_provider_models(db, editing_provider)
    runtime_target_rows = await _runtime_target_rows(db, config, active_provider)
    return {
        "request": request,
        "config": config,
        "providers": providers,
        "active_provider": active_provider,
        "primary_runtime": runtime_target_rows[0] if runtime_target_rows else None,
        "runtime_targets": runtime_target_rows,
        "runtime_provider_options": _runtime_provider_options(providers, config),
        "editing_provider": editing_provider,
        "editing_provider_has_key": editing_provider_has_key,
        "editing_provider_auth_mode": get_provider_auth_mode(editing_provider),
        "editing_provider_auth_metadata": oauth_metadata_from_provider(editing_provider) if editing_provider else {},
        "copilot_auth_session": get_copilot_auth_session_info(),
        "pending_copilot_flow": _pending_copilot_flow(request, editing_provider),
        "control_plane_notice": request.query_params.get("notice", ""),
        "control_plane_error": request.query_params.get("error", ""),
        "selected_model_id": _selected_model_id(editing_provider, config),
        "models": models,
        "driver_choices": list_supported_driver_names(),
        "test_prompt": test_prompt,
        "test_response": test_response,
        "test_error": test_error,
    }


async def _build_tools_context(
    request: Request,
    db: AsyncSession,
    *,
    user: User,
    script_id: str | None = None,
    project_id: str = "",
    tool_test_results: dict[str, dict] | None = None,
) -> dict:
    scripts = await list_saved_scripts(db, active_only=False)
    editing_script = await db.get(SavedPythonScript, script_id) if script_id else None
    projects = (await db.execute(select(Project).order_by(Project.name.asc()))).scalars().all()
    tool_config_entries = await list_tool_configs(db, project_id or None)
    tool_config_forms = build_tool_config_forms(tool_config_entries, project_id or None, tool_test_results)
    for form in tool_config_forms:
        form["secret_ref_labels"] = {
            field_name: secret_ref_label(secret_id) for field_name, secret_id in form.get("secret_refs", {}).items()
        }
    built_in_tools = sorted(
        [{"name": tool.name, "description": getattr(tool, "description", "")} for tool in _tool_registry().values()],
        key=lambda item: item["name"],
    )
    return {
        "request": request,
        "user": user,
        "scripts": scripts,
        "editing_script": editing_script,
        "built_in_tools": built_in_tools,
        "projects": projects,
        "selected_project_id": project_id,
        "tool_config_forms": tool_config_forms,
        "tool_config_presets": TOOL_CONFIG_PRESETS,
    }


async def _list_agent_definitions(db: AsyncSession, *, user_id: str) -> list[AgentDefinition]:
    result = await db.execute(
        select(AgentDefinition)
        .options(selectinload(AgentDefinition.steps), selectinload(AgentDefinition.group))
        .where(await visible_agent_clause(db, user_id))
        .order_by(AgentDefinition.updated_at.desc(), AgentDefinition.name.asc())
    )
    return result.scalars().unique().all()


# The chat runtime options are owned by ``app.services.runtime_options`` (turn preparation reads them too); the
# web helpers and panel routers read them under this name.

# The agent payload builders are owned by ``app.services.agent_definition_payload``; the panel routers and admin
# contexts read them under these names (``app.web._serialize_agent_definition``).
