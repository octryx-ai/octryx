"""The Workspace runtime allowlist applied to a resolved runtime chain.

The turn's start runtime is checked when it is chosen (``turn_runtime_selection``),
but the control plane appends every other active target as the fallback chain. A
``selected_only`` Workspace must never be answered by a runtime outside its list,
so each target the Workspace does not allow is *annotated* with the generic
``admission_denial`` contract: the engine records a zero-dispatch attempt and
continues with the targets that are allowed. A chain whose targets are all
refused ends with no answer instead of a disallowed one.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ...agent.core.runtime.runtime_admission_contract import (
    RUNTIME_ADMISSION_DENIAL_KEY,
    runtime_admission_denial,
)
from ...agent.core.runtime.runtime_errors import RUNTIME_ERROR_RUNTIME_NOT_ALLOWED
from .assignment_policy import is_runtime_allowed, runtime_assignment_mode
from .execution_view import get_workspace_execution_view, normalize_workspace_execution_view

RUNTIME_NOT_ALLOWED_MESSAGE = "Runtime is not allowed by the Workspace runtime assignment policy."
RUNTIME_NOT_ALLOWED_REASON = "workspace_runtime_not_selected"


def _not_allowed_annotation(runtime: dict[str, Any]) -> dict[str, Any]:
    return {
        "error_class": RUNTIME_ERROR_RUNTIME_NOT_ALLOWED,
        "reason": RUNTIME_NOT_ALLOWED_REASON,
        "message": RUNTIME_NOT_ALLOWED_MESSAGE,
        "evidence": {"target_id": str(runtime.get("target_id") or "")},
    }


def apply_workspace_runtime_allowlist(
    runtimes: list[dict[str, Any]] | None,
    workspace_execution_view: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    """Annotate every runtime the Workspace does not allow; ``all_installed`` returns the chain unchanged.

    In ``selected_only`` mode a runtime without a target id (the environment
    fallback) is not on any list, so it is refused as well.
    """

    chain = list(runtimes or [])
    if runtime_assignment_mode(workspace_execution_view) != "selected_only":
        return chain
    admitted: list[dict[str, Any]] = []
    for runtime in chain:
        target_id = str(runtime.get("target_id") or "").strip() if isinstance(runtime, dict) else ""
        allowed = bool(target_id) and is_runtime_allowed(workspace_execution_view, runtime_target_id=target_id)
        if allowed or not isinstance(runtime, dict) or runtime_admission_denial(runtime) is not None:
            admitted.append(runtime)
            continue
        admitted.append({**runtime, RUNTIME_ADMISSION_DENIAL_KEY: _not_allowed_annotation(runtime)})
    return admitted


async def admit_workspace_runtime_chain(
    db: AsyncSession,
    runtimes: list[dict[str, Any]] | None,
    *,
    project_config: dict[str, Any] | None,
    project_id: str | None,
) -> list[dict[str, Any]]:
    """Run preparation's seam: the turn's runtime chain bounded by its Workspace allowlist."""

    view = await turn_runtime_allowlist_view(db, project_config=project_config, project_id=project_id)
    return apply_workspace_runtime_allowlist(runtimes, view)


async def turn_runtime_allowlist_view(
    db: AsyncSession,
    *,
    project_config: dict[str, Any] | None,
    project_id: str | None,
) -> dict[str, Any] | None:
    """The view the turn recorded (``project_config``), else the Workspace's current one."""

    recorded = (project_config or {}).get("workspace_execution_view")
    view = normalize_workspace_execution_view(dict(recorded)) if isinstance(recorded, dict) and recorded else None
    if view is None and project_id:
        view = normalize_workspace_execution_view(
            await get_workspace_execution_view(db, workspace_id=str(project_id), ensure_foundation=False)
        )
    return view


__all__ = [
    "RUNTIME_NOT_ALLOWED_MESSAGE",
    "RUNTIME_NOT_ALLOWED_REASON",
    "admit_workspace_runtime_chain",
    "apply_workspace_runtime_allowlist",
    "turn_runtime_allowlist_view",
]
