"""Admitted provider resolution for the CallAgent dispatch owner.

CallAgent is a registered ``admitted`` dispatch owner: it may only build a
provider client for a runtime target its own Workspace admits. The Workspace is
the CallAgent configuration row's ``project_id``, so neither the caller nor the
``model`` argument can name a project.

Kept out of ``service.py`` (already well over the file-size target) because this
is a boundary concern rather than call-flow logic: the resolution order, the
per-target refusal and the typed denial all belong together and are testable on
their own.
"""

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
    """Return the first admitted ``(client, model)`` for this CallAgent.

    A target the Workspace's ``model_policy`` refuses is skipped rather than
    raised on, so a policy gap on one runtime cannot hide a target the Workspace
    *is* allowed to use. When no target survives, the last refusal is raised as
    :class:`DispatchAdmissionDeniedError` — distinguishable from "no runtime is
    configured at all", which stays a ``RuntimeError``.
    """

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
