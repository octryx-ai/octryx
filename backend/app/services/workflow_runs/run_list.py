"""The run list without the runs' big JSON (loading every run whole made ``GET /workflow-runs?view=work`` take 75 s).

A list row needs a run's columns, two small parts of its context (``stop`` for the row, ``size_class`` for the graph's
step titles) and, per run, its main session and responsible person. A run's ``context`` carries the device change's
patches (megabytes), the last test runs with their output and every phase's facts, and ``gate_results`` every gate's
check details. So the list reads only the columns it shows plus the two context parts (one query), the main sessions and
the responsible people in one query each, and pages by ``updated_at`` (``before``) instead of growing with the
installation.
"""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import User, WorkflowRun, WorkflowRunSession

#: Never in a list: the big JSON columns (a run's page reads them, one run at a time).
HEAVY_COLUMNS = frozenset({"context", "gate_results"})
#: The parts of ``context`` a list row reads.
CONTEXT_PARTS = ("stop", "size_class", "sample_bundle", "routing")


def light_query(query: Any) -> Any:
    """``query`` (a ``select(WorkflowRun)`` with its filters) reading only the list's columns and context parts."""
    columns = [column for column in WorkflowRun.__table__.columns if column.name not in HEAVY_COLUMNS]
    parts = [WorkflowRun.context[name].label(f"context_{name}") for name in CONTEXT_PARTS]
    return query.with_only_columns(*columns, *parts)


def light_runs(rows: list[Any]) -> list[SimpleNamespace]:
    """Read-only run views for the list: every listed column, and ``context`` with only its listed parts."""
    names = [column.name for column in WorkflowRun.__table__.columns if column.name not in HEAVY_COLUMNS]
    runs = []
    for row in rows:
        values = row._mapping
        context = {name: values[f"context_{name}"] for name in CONTEXT_PARTS
                   if values[f"context_{name}"] is not None}
        runs.append(SimpleNamespace(**{name: values[name] for name in names}, context=context,
                                    gate_results={}))
    return runs


async def main_sessions(db: AsyncSession, run_ids: list[str]) -> dict[str, str]:
    """``run id -> main session`` (the newest active ``main`` link), in one query."""
    from .records import ROLE_MAIN

    if not run_ids:
        return {}
    found: dict[str, str] = {}
    for run_id, session_id in (await db.execute(
            select(WorkflowRunSession.run_id, WorkflowRunSession.session_id)
            .where(WorkflowRunSession.run_id.in_(run_ids), WorkflowRunSession.role == ROLE_MAIN,
                   WorkflowRunSession.active.is_(True))
            .order_by(WorkflowRunSession.linked_at.desc()))).all():
        found.setdefault(str(run_id), str(session_id))
    return found


async def workflow_titles(db: AsyncSession, runs: list[Any]) -> dict[str, str | None]:
    """``run id -> the workflow's title`` (its definition's name; the Workspace's own one before the shipped one), in
    one query (deriving it from the key gave titles like "Pr review bot")."""
    from ...models import FlowDefinition

    keys = sorted({str(run.workflow_key) for run in runs if run.workflow_key})
    names: dict[tuple[str | None, str], str] = {}
    if keys:
        for key, name, project_id in (await db.execute(
                select(FlowDefinition.key, FlowDefinition.name, FlowDefinition.project_id)
                .where(FlowDefinition.key.in_(keys)))).all():
            if name:
                names[(project_id, key)] = name
    return {run.id: names.get((run.project_id, run.workflow_key)) or names.get((None, run.workflow_key))
            for run in runs}


async def responsible_views(db: AsyncSession, runs: list[Any]) -> dict[str, dict[str, Any] | None]:
    """``run id -> {user_id, display_name, source}`` as ``responsible.responsible_view`` says, in one query."""
    ids = sorted({str(run.responsible_user_id) for run in runs if run.responsible_user_id})
    people = {row.id: (row.display_name or row.username) for row in (await db.execute(
        select(User.id, User.display_name, User.username).where(User.id.in_(ids)))).all()} if ids else {}
    return {run.id: ({"user_id": run.responsible_user_id, "display_name": people.get(run.responsible_user_id),
                      "source": run.responsible_source} if run.responsible_user_id else None) for run in runs}


def before_filter(query: Any, before: str | None) -> Any:
    """The page after a cursor: runs updated before ``before`` (ISO time); unchanged without one."""
    if not before:
        return query
    try:
        moment = datetime.fromisoformat(before.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return query
    return query.where(WorkflowRun.updated_at < moment)


__all__ = ["CONTEXT_PARTS", "HEAVY_COLUMNS", "before_filter", "light_query", "light_runs", "main_sessions",
           "responsible_views", "workflow_titles"]
