"""The decisions a spec-writing run introduced, recorded when it pushes the spec (finding the
spec commit by the epic key in its subject breaks on a rebase, a squash or a manual commit).

At the push of a spec-writing run (``platform/scm.push``) the run keeps ``context.spec_commit``: the pushed commit, the
spec's path and the decision texts it added or changed against the run's base. The review of a story of that work
item (the epic, its parent, or the story itself) reads it (``spec_decisions.feature_decisions``); the texts survive any
rewrite of the commit.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ....models import WorkflowRun
from ....models.runtime.secure_work import WorkItem

CONTEXT_KEY = "spec_commit"
SPEC_WORKFLOWS = ("spec-writing",)
MAX_INTRODUCED = 200


async def record_spec_commit(run: WorkflowRun, local_path: str, head: str) -> None:
    """Keep the pushed spec's introduced decisions on a spec-writing run (nothing for other runs)."""
    if run.workflow_key not in SPEC_WORKFLOWS or not local_path or not head:
        return
    from .. import safe_git
    from ..documentation.spec_source import pushed_spec
    from .spec_decisions import decision_items

    path, text = await pushed_spec(run)
    if not path:
        return
    base = str(dict(run.context or {}).get("base_sha") or "")
    code, before, _err = await safe_git.git(Path(local_path), "show", f"{base}:{path}") if base else (1, "", "")
    old = {_key(item) for item in decision_items(before if code == 0 else "")}
    introduced = [item for item in decision_items(text) if _key(item) not in old][:MAX_INTRODUCED]
    run.context = {**dict(run.context or {}), CONTEXT_KEY: {"sha": head, "path": path, "introduced": introduced}}


def _key(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


async def recorded_for(db: AsyncSession, run: WorkflowRun) -> tuple[tuple[str, ...], dict[str, Any] | None]:
    """``(keys, recorded)``: the work item's keys (epic, parent, its own) and the newest spec commit a spec-writing
    run of one of those work items recorded."""
    item = await db.get(WorkItem, run.work_item_id) if run.work_item_id else None
    if item is None:
        return (), None
    keys = tuple(dict.fromkeys(key for key in (item.epic_key, item.parent_key, item.source_key) if key))
    ids = {item.id}
    if keys:
        ids |= set((await db.execute(select(WorkItem.id).where(
            WorkItem.project_id == item.project_id, WorkItem.source_key.in_(keys)))).scalars().all())
    runs = (await db.execute(select(WorkflowRun).where(
        WorkflowRun.work_item_id.in_(ids), WorkflowRun.workflow_key.in_(SPEC_WORKFLOWS)
    ).order_by(WorkflowRun.created_at.desc()).limit(20))).scalars().all()
    for spec_run in runs:
        recorded = dict(spec_run.context or {}).get(CONTEXT_KEY)
        if isinstance(recorded, dict) and recorded.get("path"):
            return keys, recorded
    return keys, None


async def technology_catalog(db: AsyncSession, run: WorkflowRun) -> dict[str, dict[str, Any]]:
    """The technologies catalog for the run: built in under the installation's, Workspace's and repository's."""
    from ....models import Project
    from ...code_style.store import levels
    from ...code_style.technologies import catalog
    from ..platform.repo_ref import _record, parse_repository

    ref = parse_repository(run.repository)
    record = await _record(db, run, ref) if ref is not None else None
    project = await db.get(Project, run.project_id) if run.project_id else None
    return catalog(await levels(db, project=project, record=record))


__all__ = ["CONTEXT_KEY", "record_spec_commit", "recorded_for", "technology_catalog"]
