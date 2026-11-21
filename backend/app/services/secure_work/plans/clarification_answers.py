"""Answer an exact Work Plan's open questions into a new reviewable version.

Contract:

- the source plan is addressed by id and must be open and the Work Item's newest version, equal to
  the version the client saw (``expected_latest_version``); its stored workflow is loaded through the scoped
  loader (``related_rows``) for the Work Item's Workspace (missing or invisible: the same 404; an authorized
  workflow of another Workspace: the workflow mismatch 409) and must be active; otherwise a refusal before any
  model call;
- every answer names a question of the source plan by index and repeats its exact text; partial
  answers are allowed, at least one non-blank answer is required, nothing is truncated;
- the model call reuses Workspace runtime admission and runs without tools; the prompt carries the
  source plan's own bounded context (``clarification_revision``); answers are user data for the
  prompt only and never change tools, permissions, runtimes or approvals; no model parameter comes
  from this request;
- unanswered source questions stay open in the revision, whatever the model returned;
- after the model returned, the plan write lock is taken and the source is re-read; any change to
  its status, version, questions or update marker, or a newer version, refuses with 409 and
  writes nothing; only the exact source plan is superseded;
- the new plan keeps the answers in ``evidence_json["clarification"]`` and still needs review;
- an exhausted runtime chain is a 503 without provider text (see ``_is_runtime_exhaustion``).

Refusals carry a closed code as the start of ``detail`` (``<code>: <message>``).
"""

from __future__ import annotations

import dataclasses
from datetime import datetime
from typing import Any

from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ....models import User, WorkChangePlan, WorkItem, WorkItemWorkflowDefinition
from ....services.control_plane_service import resolve_control_plane_runtimes
from ....time_utils import utc_now
from ..plan_serializers import serialize_change_plan
from ..related_rows import WORKFLOW, load_related
from .clarification_revision import (
    CLARIFICATION_PROMPT_SECTION,
    clarification_prompt_section,
    refusal,
    revision_open_questions,
    source_plan_context,
    unanswered_indexes,
    validate_answers,
)
from .llm_work_plan import (
    ChatFunc,
    RuntimeResolverFunc,
    dispatch_llm_work_plan,
    store_llm_work_plan,
)
from .plan_records import OPEN_PLAN_STATUSES
from .plan_write_lock import (
    is_plan_version_conflict,
    latest_plan_version,
    lock_work_item_for_plan_write,
    reread_plan,
)

AUDIT_ACTION = "secure_work.work_plan_clarification_answered"


def _source_marker(plan: WorkChangePlan) -> tuple[Any, ...]:
    updated_at = plan.updated_at.isoformat() if isinstance(plan.updated_at, datetime) else plan.updated_at
    return (
        plan.id,
        plan.work_item_id,
        plan.version,
        plan.status,
        list(plan.open_questions_json or []),
        plan.workflow_id,
        updated_at,
    )


def _is_runtime_exhaustion(exc: RuntimeError) -> bool:
    """The engine's exhausted-chain error: a ``RuntimeError`` carrying ``runtime_attempts``.

    The class is local to ``_chat_with_runtime_fallback`` and cannot be imported; its message
    lists provider errors, so only this shape is recognised and the text is never forwarded.
    """
    return isinstance(getattr(exc, "runtime_attempts", None), list)


async def _check_source(db: AsyncSession, plan: WorkChangePlan, expected_latest_version: int) -> None:
    if plan.status not in OPEN_PLAN_STATUSES:
        raise refusal(409, "plan_not_open", f"Version {plan.version} is {plan.status} and can no longer be answered.")
    latest = await latest_plan_version(db, plan.work_item_id)
    if latest != plan.version or expected_latest_version != plan.version:
        raise refusal(
            409,
            "stale_plan_version",
            f"Version {plan.version} is not the newest version (newest is v{latest}). "
            "Reload and answer the newest version.",
        )


async def _source_workflow(
    db: AsyncSession, plan: WorkChangePlan, item: WorkItem, viewer: User
) -> WorkItemWorkflowDefinition | None:
    """The source plan's stored workflow, through the scoped loader for the item's Workspace, and active."""
    if not plan.workflow_id:
        return None
    workflow = await load_related(db, viewer, WORKFLOW, plan.workflow_id, for_workspace=item.project_id)
    if not workflow.is_active:
        raise refusal(409, "source_workflow_inactive", "The plan's workflow is inactive.")
    return workflow


def _actor_label(user: User) -> str | None:
    label = str(getattr(user, "display_name", None) or getattr(user, "username", None) or "").strip()
    return label[:200] or None


async def answer_plan_clarifications(
    db: AsyncSession,
    *,
    change_plan_id: str,
    current_user: User,
    expected_latest_version: int,
    answers: list[dict[str, Any]],
    chat_func: ChatFunc | None = None,
    runtime_resolver_func: RuntimeResolverFunc = resolve_control_plane_runtimes,
) -> dict[str, Any]:
    """Generate the next version from answers to ``change_plan_id``; the caller checked role and scope."""
    source = await reread_plan(db, change_plan_id)
    item = await db.get(WorkItem, source.work_item_id) if source is not None else None
    if source is None or item is None:
        raise HTTPException(status_code=404, detail="Change Plan not found")
    await _check_source(db, source, expected_latest_version)
    bound = validate_answers(list(source.open_questions_json or []), answers)
    workflow = await _source_workflow(db, source, item, current_user)
    marker = _source_marker(source)
    context, context_record = source_plan_context(source)
    try:
        draft = await dispatch_llm_work_plan(
            db,
            item=item,
            workflow=workflow,
            payload={},
            chat_func=chat_func,
            runtime_resolver_func=runtime_resolver_func,
            clarification_section=clarification_prompt_section(source, bound, context, context_record),
        )
    except RuntimeError as exc:
        if not _is_runtime_exhaustion(exc):
            raise
        raise refusal(
            503, "plan_generation_unavailable", "No admitted runtime produced a Work Plan. Your answers were not saved."
        ) from None

    await lock_work_item_for_plan_write(db, item.id)
    current = await reread_plan(db, source.id)
    if (
        current is None
        or _source_marker(current) != marker
        or await latest_plan_version(db, item.id) != source.version
    ):
        raise refusal(
            409,
            "plan_changed_during_generation",
            f"Version {marker[2]} changed while the revised plan was generated. Nothing was saved; reload and retry.",
        )
    open_questions, carried = revision_open_questions(current, bound, list(draft.plan_data["open_questions"]))
    draft = dataclasses.replace(draft, plan_data={**draft.plan_data, "open_questions": open_questions})
    now = utc_now()
    current.status = "superseded"
    current.updated_by = current_user.id
    current.decided_by = current_user.id
    current.decided_at = now
    clarification = {
        "source_plan_id": current.id,
        "source_version": current.version,
        "prompt_section": CLARIFICATION_PROMPT_SECTION,
        "answered_by": current_user.id,
        "answered_by_label": _actor_label(current_user),
        "answered_at": now.isoformat(),
        "answers": bound,
        "unanswered_question_indexes": unanswered_indexes(current, bound),
        "carried_open_questions": carried,
        "source_context": context_record,
    }
    try:
        row = await store_llm_work_plan(
            db,
            item=item,
            workflow=workflow,
            draft=draft,
            current_user=current_user,
            version=current.version + 1,
            supersedes_plan_id=current.id,
            payload={},
            audit_action=AUDIT_ACTION,
            extra_evidence={"clarification": clarification},
            extra_audit={
                "source_plan_id": current.id,
                "source_version": current.version,
                "answer_count": len(bound),
                "carried_question_count": len(carried),
            },
        )
    except IntegrityError as exc:
        if not is_plan_version_conflict(exc):
            raise
        raise refusal(
            409,
            "plan_version_conflict",
            "Another version was saved at the same time. Nothing was saved; reload and retry.",
        ) from None
    return serialize_change_plan(row)
