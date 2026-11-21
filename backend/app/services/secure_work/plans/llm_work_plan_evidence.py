"""Evidence, usage, approvals and Jira sync preview recorded with a model-authored Work Plan."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ....models import (
    WorkChangePlan,
    WorkItem,
    WorkItemWorkflowDefinition,
)
from ....services.budget import compute_usage_event_cost
from .llm_work_plan_prompt import WORK_PLAN_PROMPT_VERSION, _objects
from .plan_records import _jira_sync_preview


def _merge_required_approvals(plan_data: dict[str, Any], reviewer_payload: dict[str, Any]) -> list[dict[str, Any]]:
    approvals = _objects(plan_data.get("required_approvals"))
    if not approvals:
        approvals = [
            {
                "type": "work_plan",
                "required": True,
                "reason": "Human approval is required before execution.",
            }
        ]
    if plan_data.get("plan_type") in {"coding_change", "configuration_change"}:
        approvals.append(
            {
                "type": "code_review",
                "required": True,
                "reason": "Repository or configuration changes require human review.",
            }
        )
    recommendations = list(reviewer_payload.get("recommendations") or [])[:3]
    if recommendations:
        approvals.append(
            {
                "type": "recommended_reviewer",
                "required": False,
                "reviewers": [entry["display_name"] for entry in recommendations],
            }
        )
    return approvals


def _llm_evidence(
    *,
    item: WorkItem,
    workflow: WorkItemWorkflowDefinition | None,
    response: dict[str, Any],
    runtime: dict[str, Any],
    attempts: list[dict[str, Any]],
    plan_data: dict[str, Any],
    raw_content: str,
    usage_summary: dict[str, Any],
) -> dict[str, Any]:
    return {
        "author": "llm",
        "prompt_version": WORK_PLAN_PROMPT_VERSION,
        "plan_type": plan_data["plan_type"],
        "runtime": {
            "target_id": runtime.get("target_id"),
            "provider_id": runtime.get("provider_id"),
            "provider": runtime.get("provider_name") or runtime.get("provider"),
            "driver": runtime.get("driver"),
            "model": runtime.get("model"),
            "priority": runtime.get("priority"),
        },
        "usage": dict(response.get("usage") or {}),
        "usage_summary": usage_summary,
        "attempts": attempts,
        "raw_response_preview": raw_content[:8000],
        "work_item": {
            "source_type": item.source_type,
            "source_instance": item.source_instance,
            "source_key": item.source_key,
            "source_status": item.source_status,
            "work_state": item.work_state,
            "labels": list(item.labels_json or []),
            "fix_versions": list(item.fix_versions_json or []),
        },
        "workflow": {"id": workflow.id, "name": workflow.name} if workflow else None,
    }


async def _llm_usage_summary(
    db: AsyncSession,
    *,
    response: dict[str, Any],
    runtime: dict[str, Any],
) -> dict[str, Any]:
    usage = dict(response.get("usage") or {})
    tokens_in = _usage_prompt_tokens(usage)
    tokens_out = _safe_usage_int(usage.get("completion_tokens") or usage.get("outputTokens"))
    total_tokens = _safe_usage_int(usage.get("total_tokens") or usage.get("totalTokens")) or tokens_in + tokens_out
    provider = str(runtime.get("provider_name") or runtime.get("provider") or "").strip()
    model = str(runtime.get("model") or "").strip()
    estimated_cost = Decimal("0")
    if provider and model:
        estimated_cost = await compute_usage_event_cost(
            db,
            provider=provider,
            model=model,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            usage=usage,
        )
    return {
        "provider": provider,
        "model": model,
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
        "total_tokens": total_tokens,
        "estimated_cost": float(estimated_cost),
        "request_duration_ms": _safe_usage_int(usage.get("request_duration_ms")),
        "source": "work_plan_generation",
    }


def _safe_usage_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _usage_prompt_tokens(usage: dict[str, Any]) -> int:
    prompt_tokens = _safe_usage_int(usage.get("prompt_tokens"))
    bedrock_total = _safe_usage_int(usage.get("bedrock_total_input_tokens"))
    bedrock_components = (
        _safe_usage_int(usage.get("inputTokens"))
        + _safe_usage_int(usage.get("cacheReadInputTokens"))
        + _safe_usage_int(usage.get("cacheWriteInputTokens"))
    )
    return max(prompt_tokens, bedrock_total, bedrock_components)


def _llm_jira_sync_preview(
    *,
    item: WorkItem,
    plan: WorkChangePlan,
    workflow: WorkItemWorkflowDefinition | None,
    target_state: str,
    approval_base_url: str | None,
) -> dict[str, Any]:
    preview = _jira_sync_preview(workflow=workflow, target_state=target_state, source="llm_work_plan_generation")
    approval_url = _approval_url(plan, approval_base_url=approval_base_url)
    comment_body = (
        f"Octryx Work Plan v{plan.version} is ready for review.\n\n"
        f"*Work Item:* {item.source_key} - {item.title}\n"
        f"*Plan type:* {dict(plan.evidence_json or {}).get('plan_type', 'unknown')}\n"
        f"*Status:* {plan.status}\n\n"
        f"Review and approve here: {approval_url}"
    )
    return {
        **preview,
        "comment_body": comment_body,
        "approval_url": approval_url,
        "will_mutate_jira": False,
    }


def _approval_url(plan: WorkChangePlan, *, approval_base_url: str | None) -> str:
    base = (approval_base_url or "/chat").rstrip("/")
    separator = "&" if "?" in base else "?"
    return f"{base}{separator}area=work&work_item_id={plan.work_item_id}&change_plan_id={plan.id}"
