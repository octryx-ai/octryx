"""The runtime options a chat turn may select: the automatic chain plus every ready target.

Turn preparation (``services/session``) and the chat UI read this one list. A Workspace with
``runtime_assignment_mode=selected_only`` sees only its bound targets and no automatic entry; a
provider that is inactive is dropped, one that is not ready is listed as disabled with its reason.

The automatic entry names the model the turn will actually start on: the Workspace default, else the first target
of the platform order, that the model resolver's gates admit (``model_selection.gates``: enabled in the Model
catalog, provider on, allowed in the Workspace including its ``model_policy`` alias grant, cleared for its data class)
on a ready provider. A target those gates refuse is listed as disabled, naming the reason.
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ..models import ControlPlaneRuntimeTarget, LLMModel, LLMProvider
from .control_plane_service import ensure_control_plane_defaults, get_runtime_targets
from .model_selection.gates import WorkspaceScope, gate, reason_text
from .model_selection.snapshot import SelectionSnapshot, load_scope, load_snapshot
from .provider import resolve_provider_readiness
from .system_config import get_agent_default_model
from .workspace_composition.assignment_policy import runtime_assignment_mode, selected_runtime_target_ids
from .workspace_composition.execution_view import normalize_workspace_execution_view


async def load_runtime_option_providers(db: AsyncSession, provider_ids: set[str]) -> dict[str, LLMProvider]:
    # Readiness reads credential state from the provider-owned oauth_config row;
    # it must be eager-loaded or the provider would look unconfigured.
    if not provider_ids:
        return {}
    result = await db.execute(
        select(LLMProvider)
        .options(selectinload(LLMProvider.oauth_config))
        .where(LLMProvider.id.in_(provider_ids))
    )
    return {provider.id: provider for provider in result.scalars().all()}


def runtime_not_ready_reason(provider: LLMProvider) -> str:
    readiness = resolve_provider_readiness(provider)
    if readiness.get("runtime_attempt_allowed") is False:
        return f"Provider is not ready: {readiness.get('reason') or readiness.get('status')}."
    return ""


async def catalog_display_name(db: AsyncSession, provider_id: str, model_id: str) -> str:
    """The Model catalog display name; the provider model id only when no row names it."""
    name = (
        await db.execute(
            select(LLMModel.display_name).where(LLMModel.provider_id == provider_id, LLMModel.model_id == model_id)
        )
    ).scalars().first()
    return str(name or model_id)


async def serialize_runtime_target_option(
    db: AsyncSession,
    target: ControlPlaneRuntimeTarget,
    *,
    disabled: bool = False,
    disabled_reason: str = "",
    provider: LLMProvider | None = None,
) -> dict | None:
    if provider is None:
        provider = (await load_runtime_option_providers(db, {target.provider_id})).get(target.provider_id)
    if not provider or not provider.is_active:
        return None
    option = {
        "value": target.id,
        "label": await catalog_display_name(db, target.provider_id, target.model_id),
        "provider_name": provider.display_name or provider.name,
        "model_id": target.model_id,
        "is_automatic": False,
    }
    not_ready_reason = runtime_not_ready_reason(provider)
    if disabled or not_ready_reason:
        option["disabled"] = True
        option["disabled_reason"] = disabled_reason or not_ready_reason
    return option


async def _selection_scope(db: AsyncSession, workspace_execution_view: dict | None) -> WorkspaceScope:
    normalized = normalize_workspace_execution_view(workspace_execution_view) if workspace_execution_view else None
    workspace_id = str((normalized or {}).get("workspace_id") or "").strip()
    if not workspace_id:
        return WorkspaceScope()
    return await load_scope(db, workspace_id=workspace_id, view=workspace_execution_view)


def _gate_reason(snapshot: SelectionSnapshot, scope: WorkspaceScope, target: ControlPlaneRuntimeTarget) -> str:
    """Why the resolver's gates refuse the target's model here, or ``""`` (a target without a catalog row passes)."""
    model = snapshot.for_target(target.id)
    return gate(model, scope) if model is not None else ""


async def list_chat_runtime_options(
    db: AsyncSession,
    *,
    workspace_execution_view: dict | None = None,
    include_runtime_target_id: str = "",
) -> list[dict]:
    config = await ensure_control_plane_defaults(db)
    targets = await get_runtime_targets(db, config, active_only=True)
    default_model = await get_agent_default_model(db)
    selected_only = runtime_assignment_mode(workspace_execution_view) == "selected_only"
    allowed_target_ids = selected_runtime_target_ids(workspace_execution_view) if selected_only else set()
    providers = await load_runtime_option_providers(db, {target.provider_id for target in targets})
    snapshot = await load_snapshot(db)
    scope = await _selection_scope(db, workspace_execution_view)
    refused = {target.id: _gate_reason(snapshot, scope, target) for target in targets}
    automatic_label = "Automatic fallback chain"
    # The turn starts on the Workspace default when it passes the gates (``turn_runtime_selection``), else on the
    # first admitted target of the chain.
    starts = sorted(targets, key=lambda target: target.id != scope.default_target_id)
    for target in starts:
        provider = providers.get(target.provider_id)
        if not provider or not provider.is_active or runtime_not_ready_reason(provider) or refused[target.id]:
            continue
        if selected_only and target.id not in allowed_target_ids:
            continue
        automatic_label = f"Automatic · {await catalog_display_name(db, target.provider_id, target.model_id)}"
        break
    options = []
    if not selected_only:
        options.append(
            {
                "value": "",
                "label": automatic_label,
                "provider_name": "Control Plane",
                "model_id": config.model_id or default_model,
                "is_automatic": True,
            }
        )
    for target in targets:
        if selected_only and target.id not in allowed_target_ids:
            continue
        reason = refused[target.id]
        option = await serialize_runtime_target_option(
            db,
            target,
            provider=providers.get(target.provider_id),
            disabled=bool(reason),
            disabled_reason=reason_text(reason) if reason else "",
        )
        if option is not None:
            options.append(option)
    include_runtime_target_id = str(include_runtime_target_id or "").strip()
    option_ids = {str(option.get("value") or "") for option in options}
    if include_runtime_target_id and include_runtime_target_id not in option_ids:
        target = await db.get(ControlPlaneRuntimeTarget, include_runtime_target_id)
        if target is not None:
            option = await serialize_runtime_target_option(
                db,
                target,
                disabled=True,
                disabled_reason="This runtime is not allowed by the active project policy.",
            )
            if option is not None:
                options.append(option)
    return options


__all__ = [
    "list_chat_runtime_options",
    "load_runtime_option_providers",
    "runtime_not_ready_reason",
    "serialize_runtime_target_option",
]
