"""Model-authored Work Plans: dispatch to an admitted runtime, then store the parsed plan."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from ....models import (
    User,
    WorkChangePlan,
    WorkItem,
    WorkItemWorkflowDefinition,
)
from ....services.control_plane_service import resolve_control_plane_runtimes
from ....services.model_gateway.dispatch_admission import admit_runtimes_for_dispatch
from ...content_security.handling import PLATFORM_RECORD_WITHOUT_WORKSPACE
from ...content_security.model_call_scope import call_scope, model_call_scope
from ...prompt_catalog import prompt_set_scope
from ...prompt_catalog.out_of_turn import prompt_set_for
from ..jira_values import blank_to_none
from ..plan_serializers import serialize_change_plan
from ..related_rows import WORKFLOW, load_optional_related
from ..reviewers import recommend_reviewers_for_work_item
from .llm_work_plan_evidence import (
    _llm_evidence,
    _llm_jira_sync_preview,
    _llm_usage_summary,
    _merge_required_approvals,
)
from .llm_work_plan_prompt import _llm_work_plan_messages, _parse_llm_work_plan
from .plan_records import _audit_log, _next_version, _supersede_open_plans
from .plan_write_lock import lock_work_item_for_plan_write

ChatFunc = Callable[..., Awaitable[tuple[dict, dict, list[dict[str, Any]]]]]
RuntimeResolverFunc = Callable[..., Awaitable[list[dict]]]


@dataclass(frozen=True)
class LlmPlanDraft:
    """A parsed model answer, not yet versioned or stored."""

    content: str
    plan_data: dict[str, Any]
    response: dict[str, Any]
    runtime: dict[str, Any]
    attempts: list[dict[str, Any]]


async def generate_llm_work_plan(
    db: AsyncSession,
    *,
    work_item_id: str,
    current_user: User,
    payload: dict[str, Any],
    chat_func: ChatFunc | None = None,
    runtime_resolver_func: RuntimeResolverFunc = resolve_control_plane_runtimes,
) -> dict[str, Any]:
    item = await db.get(WorkItem, work_item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Work Item not found")
    workflow = await load_optional_related(
        db, current_user, WORKFLOW, blank_to_none(payload.get("workflow_id")), for_workspace=item.project_id
    )
    draft = await dispatch_llm_work_plan(
        db,
        item=item,
        workflow=workflow,
        payload=payload,
        chat_func=chat_func,
        runtime_resolver_func=runtime_resolver_func,
    )
    # The write lock is taken only after the model returned.
    await lock_work_item_for_plan_write(db, item.id)
    version = await _next_version(db, item.id)
    superseded_plan_id = await _supersede_open_plans(
        db,
        item.id,
        current_user.id,
        bool(payload.get("supersede_existing", True)),
    )
    row = await store_llm_work_plan(
        db,
        item=item,
        workflow=workflow,
        draft=draft,
        current_user=current_user,
        version=version,
        supersedes_plan_id=superseded_plan_id,
        payload=payload,
    )
    return serialize_change_plan(row)


async def dispatch_llm_work_plan(
    db: AsyncSession,
    *,
    item: WorkItem,
    workflow: WorkItemWorkflowDefinition | None,
    payload: dict[str, Any],
    chat_func: ChatFunc | None = None,
    runtime_resolver_func: RuntimeResolverFunc = resolve_control_plane_runtimes,
    clarification_section: str | None = None,
) -> LlmPlanDraft:
    """Admit Workspace runtimes, ask the model without tools and parse its Work Plan; writes nothing."""
    if chat_func is None:
        # Imported lazily: the engine must not load when the secure_work
        # package initializes (loop modules import secure_work contracts).
        from ....agent.engine import _chat_with_runtime_fallback

        chat_func = _chat_with_runtime_fallback
    runtime_target_id = blank_to_none(payload.get("runtime_target_id"))
    # The Workspace is the Work Item's own project, never a request field; a
    # gateway target its ``model_policy`` has not granted is annotated so the
    # engine records the refusal as a zero-dispatch attempt.
    admission = await admit_runtimes_for_dispatch(
        db,
        await runtime_resolver_func(db, runtime_target_id=runtime_target_id),
        project_ids=getattr(item, "project_id", None),
        owner="secure_work_plan_worker",
    )
    runtimes = list(admission.runtimes)
    if not runtimes:
        raise HTTPException(status_code=503, detail="No active runtime is configured for Work Plan generation")
    if not admission.allowed:
        raise HTTPException(status_code=503, detail=admission.to_result())
    # The Work Plan author runs outside a turn: render for the Work Item's Workspace.
    with prompt_set_scope(await prompt_set_for(db, workspace_id=getattr(item, "project_id", None))):
        messages = _llm_work_plan_messages(
            item=item, workflow=workflow, payload=payload, clarification_section=clarification_section
        )
    # The Work Item's Workspace (the one the runtimes were admitted for), or an item stored without one.
    scope = call_scope(getattr(item, "project_id", None), without_workspace=PLATFORM_RECORD_WITHOUT_WORKSPACE)
    with model_call_scope(scope):
        response, runtime, attempts = await chat_func(
            runtimes,
            messages=messages,
            tools=None,
            max_tokens=int(payload.get("max_tokens") or 2500),
            reasoning_effort=blank_to_none(payload.get("reasoning_effort")) or "low",
            request_timeout_seconds=float(payload.get("request_timeout_seconds") or 120.0),
        )
    content = str(response.get("content") or "").strip()
    plan_data = _parse_llm_work_plan(content, item=item)
    return LlmPlanDraft(content=content, plan_data=plan_data, response=response, runtime=runtime, attempts=attempts)


async def store_llm_work_plan(
    db: AsyncSession,
    *,
    item: WorkItem,
    workflow: WorkItemWorkflowDefinition | None,
    draft: LlmPlanDraft,
    current_user: User,
    version: int,
    supersedes_plan_id: str | None,
    payload: dict[str, Any],
    audit_action: str = "secure_work.llm_work_plan_generated",
    extra_evidence: dict[str, Any] | None = None,
    extra_audit: dict[str, Any] | None = None,
) -> WorkChangePlan:
    """Store a parsed Work Plan as ``version``; the caller holds the plan write lock."""
    plan_data = dict(draft.plan_data)
    response, runtime = draft.response, draft.runtime
    recommendation_payload = await recommend_reviewers_for_work_item(db, item.id, viewer=current_user,
                                                                     workspace_id=item.project_id)
    plan_data["reviewer_recommendations"] = list(recommendation_payload.get("recommendations") or [])[:5]
    plan_data["required_approvals"] = _merge_required_approvals(plan_data, recommendation_payload)
    status = "needs_clarification" if plan_data["open_questions"] else "ready_for_review"
    usage_summary = await _llm_usage_summary(db, response=response, runtime=runtime)
    evidence = _llm_evidence(
        item=item, workflow=workflow, response=response, runtime=runtime, attempts=draft.attempts,
        plan_data=plan_data, raw_content=draft.content, usage_summary=usage_summary,
    )
    row = _llm_plan_row(
        item=item,
        workflow=workflow,
        plan_data=plan_data,
        payload=payload,
        version=version,
        supersedes_plan_id=supersedes_plan_id,
        status=status,
        evidence_json={**evidence, **(extra_evidence or {})},
        current_user=current_user,
    )
    db.add(row)
    await db.flush()
    row.jira_sync_preview_json = _llm_jira_sync_preview(
        item=item,
        plan=row,
        workflow=workflow,
        target_state=str(payload.get("target_state") or status),
        approval_base_url=blank_to_none(payload.get("approval_base_url")),
    )
    audit_details = {
        "change_plan_id": row.id,
        "version": version,
        "status": status,
        "work_type": plan_data["plan_type"],
        "runtime_target_id": runtime.get("target_id"),
        "model": runtime.get("model"),
        "usage": usage_summary,
        **(extra_audit or {}),
    }
    db.add(_audit_log(current_user, item, audit_action, audit_details))
    await db.flush()
    return row


def _llm_plan_row(
    *,
    item: WorkItem,
    workflow: WorkItemWorkflowDefinition | None,
    plan_data: dict[str, Any],
    payload: dict[str, Any],
    version: int,
    supersedes_plan_id: str | None,
    status: str,
    evidence_json: dict[str, Any],
    current_user: User,
) -> WorkChangePlan:
    return WorkChangePlan(
        work_item_id=item.id,
        workflow_id=workflow.id if workflow else None,
        supersedes_plan_id=supersedes_plan_id,
        version=version,
        status=status,
        title=str(payload.get("title") or plan_data.get("title") or f"{item.source_key} Work Plan")[:500],
        understood_request=plan_data["understood_request"],
        assumptions_json=plan_data["assumptions"],
        open_questions_json=plan_data["open_questions"],
        affected_repositories_json=plan_data["affected_repositories"],
        change_units_json=[],
        proposed_branches_json=plan_data["proposed_branches"],
        planned_files_json=plan_data["planned_files"],
        validation_plan_json=plan_data["validation_plan"],
        acceptance_criteria_json=plan_data["acceptance_criteria"],
        security_risks_json=plan_data["security_risks"],
        reviewer_recommendations_json=plan_data["reviewer_recommendations"],
        required_approvals_json=plan_data["required_approvals"],
        expected_prs_json=plan_data["expected_prs"],
        rollback_plan=plan_data["rollback_plan"],
        trace_refs_json=plan_data["trace_refs"],
        evidence_json=evidence_json,
        jira_sync_preview_json={},
        created_by=current_user.id,
        updated_by=current_user.id,
    )
