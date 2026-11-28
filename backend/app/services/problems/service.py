"""The problems list: every collector over existing status rows, scoped, acknowledged items hidden."""

from __future__ import annotations

from collections import Counter
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import Project, User
from ...time_utils import utc_now
from . import activity, budgets, connections, denials, devices, intake, models_unpriced, runs, syncs, tokens
from .acknowledgements import acknowledge, acknowledged, is_hidden
from .model import KINDS, SEVERITIES, SEVERITY_ATTENTION, SEVERITY_PROBLEM, CollectContext, Problem
from .scope import ProblemScope

Collector = Callable[[AsyncSession, CollectContext], Awaitable[list[Problem]]]
COLLECTORS: tuple[Collector, ...] = (
    connections.collect, syncs.collect, intake.collect, runs.collect, denials.collect, tokens.collect,
    devices.collect, budgets.collect, models_unpriced.collect, activity.collect,
)


class ProblemsQueryError(Exception):
    def __init__(self, field: str, message: str) -> None:
        super().__init__(message)
        self.field, self.message, self.code = field, message, "invalid_filter"


def _check(field: str, value: str | None, allowed: tuple[str, ...]) -> str | None:
    value = (value or "").strip() or None
    if value is not None and value not in allowed:
        raise ProblemsQueryError(field, f"Unknown {field} '{value}'; use one of: {', '.join(allowed)}.")
    return value


async def _collect(db: AsyncSession, scope: ProblemScope, now: datetime) -> list[Problem]:
    ctx = scope.context(now)
    problems: list[Problem] = []
    for collector in COLLECTORS:
        problems.extend(await collector(db, ctx))
    ids = sorted({item.workspace_id for item in problems if item.workspace_id})
    rows = (await db.execute(select(Project.id, Project.name, Project.is_active).where(Project.id.in_(ids)))).all() \
        if ids else []
    names = {workspace_id: name for workspace_id, name, _active in rows}
    # An archived Workspace (``is_active`` false) is out of service: its problems are not listed.
    archived = {workspace_id for workspace_id, _name, active in rows if active is False}
    problems = [item for item in problems if item.workspace_id not in archived]
    for item in problems:
        item.workspace_name = names.get(item.workspace_id) if item.workspace_id else None
    return problems


def _order(problem: Problem) -> tuple:
    seen = problem.last_seen or problem.since
    return (problem.severity != SEVERITY_PROBLEM, -(seen.timestamp() if seen else 0.0), problem.key)


async def visible_problems(db: AsyncSession, user: User, scope: ProblemScope, *,
                           now: datetime | None = None) -> list[Problem]:
    acks = await acknowledged(db, user)
    problems = [item for item in await _collect(db, scope, now or utc_now()) if not is_hidden(item, acks)]
    return sorted(problems, key=_order)


async def list_problems(db: AsyncSession, user: User, scope: ProblemScope, *, kind: str | None = None,
                        severity: str | None = None, now: datetime | None = None) -> dict[str, Any]:
    kind, severity = _check("kind", kind, KINDS), _check("severity", severity, SEVERITIES)
    problems = await visible_problems(db, user, scope, now=now)
    by_severity = Counter(item.severity for item in problems)
    shown = [item for item in problems
             if (kind is None or item.kind == kind) and (severity is None or item.severity == severity)]
    return {
        "problems": [item.to_dict() for item in shown],
        "counts": {SEVERITY_PROBLEM: by_severity[SEVERITY_PROBLEM],
                   SEVERITY_ATTENTION: by_severity[SEVERITY_ATTENTION],
                   "by_kind": dict(Counter(item.kind for item in problems))},
    }


async def acknowledge_problem(db: AsyncSession, user: User, scope: ProblemScope, key: str) -> Problem | None:
    problem = next((item for item in await visible_problems(db, user, scope) if item.key == key), None)
    if problem is not None:
        await acknowledge(db, user, problem)
    return problem


__all__ = ["COLLECTORS", "ProblemsQueryError", "acknowledge_problem", "list_problems", "visible_problems"]
