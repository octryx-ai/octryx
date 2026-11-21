"""The resolver's gates applied to a turn's runtime chain (the allowlist bound included).

Every runtime of the chain that may not answer in this Workspace is *annotated* with the generic
``admission_denial`` contract (error class ``runtime_not_allowed``): the engine records a zero-dispatch attempt and
continues with the runtimes that may answer, so fallback never leaves the Workspace's allowed, cleared models. The
gates are the resolver's (``gates.gate``) and hold for every driver: a direct Bedrock model that is not cleared
for a Confidential Workspace is refused exactly like a gateway alias. A gateway alias the Workspace's
``model_policy`` does not grant is left to the gateway admission (``model_alias_not_granted_for_project``); the
resolver and the chat label skip it through the same gate (``gates.alias_granted``).
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ...agent.core.runtime.runtime_admission_contract import (
    RUNTIME_ADMISSION_DENIAL_KEY,
    runtime_admission_denial,
)
from ...agent.core.runtime.runtime_errors import RUNTIME_ERROR_RUNTIME_NOT_ALLOWED
from ..workspace_composition.runtime_chain_admission import (
    apply_workspace_runtime_allowlist,
    turn_runtime_allowlist_view,
)
from .gates import REASON_ALIAS_NOT_GRANTED, REASON_NOT_ALLOWED, WorkspaceScope, gate, reason_text
from .snapshot import SelectionSnapshot, load_scope, load_snapshot


def _denial(runtime: dict[str, Any], reason: str) -> dict[str, Any]:
    return {
        "error_class": RUNTIME_ERROR_RUNTIME_NOT_ALLOWED,
        "reason": reason,
        "message": reason_text(reason),
        "evidence": {"target_id": str(runtime.get("target_id") or ""), "model": str(runtime.get("model") or "")},
    }


def apply_model_gates(
    runtimes: list[dict[str, Any]] | None,
    snapshot: SelectionSnapshot,
    scope: WorkspaceScope,
    *,
    view: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Annotate each runtime the resolver's gates refuse; already-refused runtimes stay as they are."""
    chain = apply_workspace_runtime_allowlist(runtimes, view)
    admitted: list[dict[str, Any]] = []
    for runtime in chain:
        if not isinstance(runtime, dict) or runtime_admission_denial(runtime) is not None:
            admitted.append(runtime)
            continue
        target_id = str(runtime.get("target_id") or "").strip()
        if not target_id or target_id not in snapshot.by_target:
            # Not a platform-order target: the environment runtime of an install without any target, or a runtime
            # built outside the control plane. Every selection target has a catalog row (the order listener creates
            # one, even for targets created outside the control plane), so a chain resolved from the platform order is
            # always gated here.
            admitted.append(runtime)
            continue
        model = snapshot.for_target(target_id)
        reason = gate(model, scope)
        if reason in (REASON_NOT_ALLOWED, REASON_ALIAS_NOT_GRANTED):
            # The allowlist decision above is authoritative (target ids); the ``model_policy`` grant is the
            # gateway admission's, which refuses the alias with its own auditable reason (and Cedar's).
            reason = ""
        admitted.append({**runtime, RUNTIME_ADMISSION_DENIAL_KEY: _denial(runtime, reason)} if reason else runtime)
    return admitted


async def admit_runtime_chain(
    db: AsyncSession,
    runtimes: list[dict[str, Any]] | None,
    *,
    project_config: dict[str, Any] | None,
    project_id: str | None,
    session_metadata: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Run preparation's seam: the turn's chain bounded by the Workspace's allowed, cleared, enabled models."""
    view = await turn_runtime_allowlist_view(db, project_config=project_config, project_id=project_id)
    scope = await load_scope(db, workspace_id=project_id, view=view, session_metadata=session_metadata)
    return apply_model_gates(runtimes, await load_snapshot(db), scope, view=view)


__all__ = ["admit_runtime_chain", "apply_model_gates"]
