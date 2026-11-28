"""The run list without the runs' big JSON columns, which are too slow to load for every row."""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import User, WorkflowRun, WorkflowRunSession

#: Never in a list: the big JSON columns (a run's page reads them, one run at a time).
HEAVY_COLUMNS = frozenset({"context", "gate_results"})
CONTEXT_PARTS = ("stop", "size_class", "sample_bundle", "routing")


def light_query(query: Any) -> Any:
    # The mapped attributes, not the table's columns: the Workspace filter attaches to the mapped entity only.
    columns = [getattr(WorkflowRun, prop.key).label(prop.columns[0].name)
               for prop in WorkflowRun.__mapper__.column_attrs if prop.columns[0].name not in HEAVY_COLUMNS]
    parts = [WorkflowRun.context[name].label(f"context_{name}") for name in CONTEXT_PARTS]
    return query.with_only_columns(*columns, *parts)


def light_runs(rows: list[Any]) -> list[SimpleNamespace]:
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
    ids = sorted({str(run.responsible_user_id) for run in runs if run.responsible_user_id})
    people = {row.id: (row.display_name or row.username) for row in (await db.execute(
        select(User.id, User.display_name, User.username).where(User.id.in_(ids)))).all()} if ids else {}
    return {run.id: ({"user_id": run.responsible_user_id, "display_name": people.get(run.responsible_user_id),
                      "source": run.responsible_source} if run.responsible_user_id else None) for run in runs}


def before_filter(query: Any, before: str | None) -> Any:
    if not before:
        return query
    try:
        moment = datetime.fromisoformat(before.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return query
    return query.where(WorkflowRun.updated_at < moment)


__all__ = ["CONTEXT_PARTS", "HEAVY_COLUMNS", "before_filter", "light_query", "light_runs", "main_sessions",
           "responsible_views", "workflow_titles"]
