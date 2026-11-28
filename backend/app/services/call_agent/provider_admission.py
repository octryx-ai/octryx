"""Admitted provider resolution for the CallAgent dispatch owner."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ..model_gateway.dispatch_admission import DispatchAdmissionDeniedError

# The registered provider-dispatch owner key
# (``services/model_gateway/dispatch_owners.py``).
DISPATCH_OWNER = "call_agent"

DEFAULT_MODEL = "claude-sonnet-4-6"


async def resolve_admitted_provider(
    db: AsyncSession,
    *,
    project_id: Any,
    configured_model: str | None,
    model: str | None = None,
) -> tuple[Any, str]:
    # Imported at call time: the control-plane and provider packages pull large
    # dependency graphs, and the call-flow tests substitute them here.
    from ...agent.providers import get_provider
    from ...models import LLMProvider
    from ...services.control_plane_service import (
        build_provider_client_kwargs_async,
        ensure_control_plane_defaults,
        get_runtime_targets,
    )
    from ...services.model_gateway.dispatch_admission import admit_client_kwargs_for_dispatch

    cp_config = await ensure_control_plane_defaults(db)
    last_denial: DispatchAdmissionDeniedError | None = None
    for target in await get_runtime_targets(db, cp_config, active_only=True):
        provider = await db.get(LLMProvider, target.provider_id)
        if not (provider and provider.is_active):
            continue
        resolved_model = model or target.model_id or configured_model or DEFAULT_MODEL
        admission = await admit_client_kwargs_for_dispatch(
            db,
            await build_provider_client_kwargs_async(db, provider),
            model=resolved_model,
            project_ids=project_id,
            owner=DISPATCH_OWNER,
        )
        if not admission.allowed:
            last_denial = DispatchAdmissionDeniedError(admission)
            continue
        return get_provider(**(admission.first_dispatchable_runtime() or {})), resolved_model

    if last_denial is not None:
        raise last_denial
    raise RuntimeError("No LLM runtime available for CallAgent — configure a provider in the control plane")


__all__ = ["DEFAULT_MODEL", "DISPATCH_OWNER", "resolve_admitted_provider"]
