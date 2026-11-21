"""The Definition of Ready of a Work item (Jira intake & triage; replaces the regex clarification gate).

The triage phase's agent submits one structured record (``submit_definition_of_ready``, a phase output:
``phase_outputs``); the server validates it and keeps it on the run (``context.definition_of_ready``):

``{"type": "feature" | "bug" | "task" | "incident", "summary", "acceptance_criteria": [...],
"reproduction_steps": [...], "expected", "actual", "repository": "<provider>:<path>", "open_questions": [...]}``

It is **complete** when a feature names acceptance criteria, a bug its reproduction steps and the expected and
actual behaviour, the affected repository is a valid reference, and no question is open. The ``definition_of_ready``
check passes only on a complete record; a person then confirms the item is ready (the workflow's confirmation), and
only a run that ended through that confirmation counts as a confirmed Definition of Ready
(:func:`confirmed_ready`) — e.g. for a scheduled coding run's clarification gate.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import WorkflowRun
from ...time_utils import utc_now

DOR_KEY = "definition_of_ready"
TRIAGE_WORKFLOW_KEY = "jira-intake-triage"
# ``incident``: routed to the incident analysis; it needs no type-specific facts.
TYPES = ("feature", "bug", "task", "incident")
MAX_ITEMS = 30


def _texts(value: Any) -> list[str]:
    return [str(item).strip()[:500] for item in value or [] if str(item).strip()][:MAX_ITEMS] if isinstance(
        value, list) else []


def validate_record(raw: Any) -> dict[str, Any]:
    """The cleaned record with ``complete`` and ``missing`` (what keeps it from being ready)."""
    from .platform.repo_ref import parse_repository

    raw = raw if isinstance(raw, dict) else {}
    record = {
        "type": str(raw.get("type") or "").strip().lower(), "summary": str(raw.get("summary") or "").strip()[:1000],
        "acceptance_criteria": _texts(raw.get("acceptance_criteria")),
        "reproduction_steps": _texts(raw.get("reproduction_steps")),
        "expected": str(raw.get("expected") or "").strip()[:1000],
        "actual": str(raw.get("actual") or "").strip()[:1000],
        "repository": str(raw.get("repository") or "").strip()[:500],
        "open_questions": _texts(raw.get("open_questions")),
    }
    missing = []
    if record["type"] not in TYPES:
        missing.append(f"type (one of {', '.join(TYPES)})")
    if record["type"] == "feature" and not record["acceptance_criteria"]:
        missing.append("acceptance criteria")
    if record["type"] == "bug":
        missing += [name for name, value in (("reproduction steps", record["reproduction_steps"]),
                                             ("expected behaviour", record["expected"]),
                                             ("actual behaviour", record["actual"])) if not value]
    if parse_repository(record["repository"]) is None:
        missing.append("affected repository (<provider>:<owner>/<repo>)")
    missing += [f"open question: {question}" for question in record["open_questions"]]
    return {**record, "complete": not missing, "missing": missing}


def apply_record(run: WorkflowRun, context: dict[str, Any], record: dict[str, Any]) -> None:
    """Keep a validated record where its readers look (``context.definition_of_ready``, the run's repository)."""
    context[DOR_KEY] = {**record, "at": utc_now().isoformat()}
    if record["complete"] and not run.repository:
        run.repository = record["repository"]


async def confirmed_ready(db: AsyncSession, work_item_id: str | None) -> bool:
    """A triage run of the item ended through the person's "ready" confirmation (outcome ``done``)."""
    if not work_item_id:
        return False
    row = (await db.execute(select(WorkflowRun.id).where(
        WorkflowRun.work_item_id == work_item_id, WorkflowRun.workflow_key == TRIAGE_WORKFLOW_KEY,
        WorkflowRun.status == "completed", WorkflowRun.outcome == "done").limit(1))).first()
    return row is not None


async def default_repository(db: AsyncSession, work_item_id: str | None, project_id: str | None) -> str | None:
    """The repository a run works on when its start names none: the item's confirmed Definition of Ready, else the
    Workspace's only active repository record (several: none — the person names it)."""
    from ...models import CodeRepository

    if work_item_id:
        rows = (await db.execute(select(WorkflowRun.context).where(
            WorkflowRun.work_item_id == work_item_id, WorkflowRun.workflow_key == TRIAGE_WORKFLOW_KEY,
            WorkflowRun.status == "completed", WorkflowRun.outcome == "done",
        ).order_by(WorkflowRun.completed_at.desc()).limit(1))).scalars().all()
        record = dict(dict(rows[0] or {}).get(DOR_KEY) or {}) if rows else {}
        if record.get("complete") and record.get("repository"):
            return str(record["repository"])
    if not project_id:
        return None
    repositories = (await db.execute(select(CodeRepository).where(
        CodeRepository.project_id == project_id, CodeRepository.is_active.is_(True)).limit(2))).scalars().all()
    if len(repositories) == 1 and repositories[0].provider in ("github", "gitlab", "bitbucket"):
        return f"{repositories[0].provider}:{repositories[0].name}"
    return None


__all__ = ["DOR_KEY", "TRIAGE_WORKFLOW_KEY", "apply_record", "confirmed_ready", "default_repository", "validate_record"]
