"""A run-bound gateway session's run context for metrics (token metrics fully attributed without
reading the database at scrape time).

``Session.metadata["attribution"]``: ``run``, ``ticket`` (the Work item's key), ``workflow``, ``workspace``, ``epic``
(the item's epic, else its parent), ``role`` (``spec`` for spec-writing, ``review`` for a reviewer session, else
``work``), ``item`` (a teamwork item's key) and ``phase`` (the run's current node). Kept when the session binds
(``attach``) and on every node entry of its run; the gateway's session resolution puts it into
``observability.attribution`` for the request.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from ....models import Session, WorkflowRun
from ....models.runtime.secure_work import WorkItem

METADATA_KEY = "attribution"
SPEC_WORKFLOW = "spec-writing"
REVIEW_PURPOSE = "workflow_run_review"


def _role(run: WorkflowRun, session: Session) -> str:
    if str((session.metadata_ or {}).get("purpose") or "") == REVIEW_PURPOSE:
        return "review"
    return "spec" if str(run.workflow_key or "") == SPEC_WORKFLOW else "work"


async def stamp(db: AsyncSession, run: WorkflowRun, session: Session, *, item: str = "") -> None:
    """Write the session's run context (when it binds to ``run``)."""
    work = await db.get(WorkItem, run.work_item_id) if run.work_item_id else None
    labels = {
        "run": run.id, "workflow": str(run.workflow_key or ""), "workspace": str(run.project_id or ""),
        "ticket": str(getattr(work, "source_key", "") or ""),
        "epic": str(getattr(work, "epic_key", "") or getattr(work, "parent_key", "") or ""),
        "role": _role(run, session), "item": item, "phase": str(run.current_node_id or ""),
    }
    session.metadata_ = {**dict(session.metadata_ or {}), METADATA_KEY: {k: v for k, v in labels.items() if v}}
    flag_modified(session, "metadata_")


async def moved_to(db: AsyncSession, run: WorkflowRun) -> None:
    """The run entered a node: its bound sessions' ``phase`` follows."""
    from ....models import WorkflowRunSession

    sessions = (await db.execute(select(Session).join(
        WorkflowRunSession, WorkflowRunSession.session_id == Session.id).where(
        WorkflowRunSession.run_id == run.id, WorkflowRunSession.active.is_(True)))).scalars().all()
    for session in sessions:
        labels = dict((session.metadata_ or {}).get(METADATA_KEY) or {})
        if labels.get("run") != run.id or labels.get("phase") == run.current_node_id:
            continue
        labels["phase"] = str(run.current_node_id or "")
        session.metadata_ = {**dict(session.metadata_ or {}), METADATA_KEY: labels}
        flag_modified(session, "metadata_")


def use_for(session: Any) -> None:
    """The request's attribution from its resolved session (``observability.attribution``)."""
    from ...observability import attribution

    labels = (getattr(session, "metadata_", None) or {}).get(METADATA_KEY)
    attribution.use(**(labels if isinstance(labels, dict) else {}))


__all__ = ["METADATA_KEY", "moved_to", "stamp", "use_for"]
