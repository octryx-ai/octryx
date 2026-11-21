"""The review call's inputs: the reviewer model, the run's working copy and the screens to show."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ....models import WorkflowRun


async def _working_copy(db: AsyncSession, run: WorkflowRun) -> Any:
    """The reviewed working copy (what decides whether a finding's file exists outside the change)."""
    from pathlib import Path

    from ..test_runs import working_copy_root

    local = str(dict(run.context or {}).get("local_path") or "")
    if local and Path(local).is_dir():
        return Path(local)
    try:
        return await working_copy_root(db, run)
    except Exception:  # noqa: BLE001 - no working copy only means no existence check (unsure: keep)
        return None


async def _review_model(factory: Any, db: AsyncSession, run: WorkflowRun, setup: Any, choice: Any) -> Any:
    """The review model for ``choice`` (``review.choice``: engine, model, route); a factory that takes no choice (a
    test's scripted reviewer) gets what it takes."""
    import inspect

    parameters = inspect.signature(factory).parameters
    extra = {key: value for key, value in (("model", choice.model), ("choice", choice), ("run", run))
             if key in parameters}
    return await factory(db, project_id=run.project_id, reviewer=setup, **extra)


def _screens(run: WorkflowRun, config: dict[str, Any], review: Any = None, root: Any = None) -> list[Any]:
    """The reviewed pass's screenshots when the review node asks for them (``config.screens``): only the review's
    screens node of this pass (``collect``), and only those of this change (``of_change``)."""
    if config.get("screens") is not True:
        return []
    from .screens import collect, of_change

    try:
        # The pipeline's screenshots when the definition names its node (``screens_node``), else the phase's.
        shots = collect(run, str(config.get("screens_node") or config.get("phase") or ""))
        if review is None:
            return shots
        return of_change(shots, diff=review.diff, changed=review.changed, root=root)
    except OSError:
        return []
