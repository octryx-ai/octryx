"""Serializers for thread rows, thread stats, workflow ROI, budget and exec policies and runtime labels."""



from ...models import (
    BudgetPolicy,
    ExecPolicyConfig,
)
from ...models import (
    Session as AgentSession,
)
from ...services.exec_policy import normalize_exec_policy_config
from .serialization import _serialize_timestamp, _sort_datetime_value

__all__ = [
    "_session_is_pinned",
    "_thread_row_sort_key",
    "_serialize_thread_row",
    "_serialize_thread_stats",
    "_serialize_budget_policy",
    "_serialize_exec_policy_config",
    "_format_message_runtime_label",
]


def _session_is_pinned(session: AgentSession | None) -> bool:
    metadata = session.metadata_ if session and isinstance(session.metadata_, dict) else {}
    return bool(metadata.get("pinned"))


def _thread_row_sort_key(row: dict) -> tuple[int, float]:
    activity = row.get("last_activity_at") or row.get("started_at")
    return (1 if bool(row.get("is_pinned")) else 0, _sort_datetime_value(activity))


def _serialize_thread_row(row: dict) -> dict:
    return {
        "id": row["id"],
        "threadNumber": int(row.get("thread_number") or 0),
        "title": row["title"],
        "preview": row["preview"],
        "messageCount": row["message_count"],
        "approvalCount": int(row.get("approval_count") or 0),
        "pendingApprovalCount": int(row.get("pending_approval_count") or 0),
        "projectName": row["project_name"],
        "runtimeLabel": row["runtime_label"],
        "startedAt": _serialize_timestamp(row["started_at"]),
        "lastActivityAt": _serialize_timestamp(row.get("last_activity_at") or row["started_at"]),
        # Device runs: the owner's own device name only, with the engine of the newest
        # job, the profile (seat / governed) and the model for the phone's run line.
        "executionTarget": (
            {"kind": "device", "deviceName": row["execution_target"]["device_name"],
             "engine": row["execution_target"].get("engine"), "profile": row["execution_target"].get("profile"),
             "model": row["execution_target"].get("model")}
            if row.get("execution_target")
            else None
        ),
        "isSelected": row["is_selected"],
        "status": row["status"],
        "runStatus": row.get("run_status") or "",
        "runCompletionReason": row.get("run_completion_reason") or "",
        "stopReason": row.get("stop_reason"),
        # The newest turn trace recorded an explicit runtime stop (additive; False when unknown).
        "latestTurnStopped": bool(row.get("latest_turn_stopped")),
        # The closed runtime stop reason of that stop (``RUNTIME_STOP_REASONS``), else null; never content.
        "latestTurnStopReason": row.get("latest_turn_stop_reason") or None,
        "isPinned": bool(row.get("is_pinned")),
        "parentSessionId": row.get("parent_session_id") or None,
        "isSubThread": bool(row.get("parent_session_id")),
        "subThreadCount": int(row.get("sub_thread_count") or 0),
        "subThreads": [_serialize_thread_row(child) for child in row.get("sub_threads") or []],
    }


def _serialize_thread_stats(stats: dict | None) -> dict | None:
    if not stats:
        return None
    cost_by_model = []
    for row in stats.get("cost_by_model") or []:
        if not isinstance(row, dict):
            continue
        cost_by_model.append(
            {
                "provider": row.get("provider") or "",
                "model": row.get("model") or "",
                "requestCount": int(row.get("request_count") or 0),
                "inputTokens": int(row.get("input_tokens") or 0),
                "outputTokens": int(row.get("output_tokens") or 0),
                "cost": float(row.get("cost") or 0),
            }
        )
    return {
        "contextTokens": int(stats.get("context_tokens") or 0),
        "inputTokens": int(stats.get("input_tokens") or 0),
        "outputTokens": int(stats.get("output_tokens") or 0),
        "cacheReadInputTokens": int(stats.get("cache_read_input_tokens") or 0),
        "cacheWriteInputTokens": int(stats.get("cache_write_input_tokens") or 0),
        "nonCachedInputTokens": int(stats.get("non_cached_input_tokens") or 0),
        "totalCost": float(stats.get("total_cost") or 0),
        "costByModel": cost_by_model,
        "requestCount": int(stats.get("request_count") or 0),
        "llmRequestCount": int(stats.get("llm_request_count") or stats.get("request_count") or 0),
        "toolCallCount": int(stats.get("tool_call_count") or 0),
        "turnTraceCount": int(stats.get("turn_trace_count") or 0),
        "deterministicStepCount": int(stats.get("deterministic_step_count") or 0),
        "zeroCostReason": stats.get("zero_cost_reason") or "",
        "workflowRoi": _serialize_workflow_roi(stats.get("workflow_roi")),
        "messageCount": int(stats.get("message_count") or 0),
        "userMessageCount": int(stats.get("user_message_count") or 0),
        "assistantMessageCount": int(stats.get("assistant_message_count") or 0),
        "lastModel": stats.get("last_model") or "",
        "lastProvider": stats.get("last_provider") or "",
    }


def _serialize_workflow_roi(roi: object) -> dict | None:
    if not isinstance(roi, dict):
        return None
    return {
        "status": roi.get("status") or "",
        "workflowId": roi.get("workflow_id") or "",
        "workflowClass": roi.get("workflow_class") or "",
        "baselineSampleCount": int(roi.get("baseline_sample_count") or 0),
        "current": _serialize_workflow_roi_metrics(roi.get("current")),
        "baseline": _serialize_workflow_roi_metrics(roi.get("baseline")),
        "savings": _serialize_workflow_roi_savings(roi.get("savings")),
        "quality": _serialize_workflow_roi_quality(roi.get("quality")),
    }


def _serialize_workflow_roi_metrics(metrics: object) -> dict:
    row = metrics if isinstance(metrics, dict) else {}
    return {
        "inputTokens": int(row.get("input_tokens") or 0),
        "outputTokens": int(row.get("output_tokens") or 0),
        "totalTokens": int(row.get("total_tokens") or 0),
        "totalCost": float(row.get("total_cost") or 0),
        "llmRequestCount": int(row.get("llm_request_count") or 0),
        "toolCallCount": int(row.get("tool_call_count") or 0),
        "deterministicStepCount": int(row.get("deterministic_step_count") or 0),
    }


def _serialize_workflow_roi_savings(savings: object) -> dict:
    row = savings if isinstance(savings, dict) else {}
    return {
        "tokenDelta": int(row.get("token_delta") or 0),
        "tokenReductionPercent": float(row.get("token_reduction_percent") or 0),
        "costDelta": float(row.get("cost_delta") or 0),
        "costReductionPercent": float(row.get("cost_reduction_percent") or 0),
        "llmRequestDelta": int(row.get("llm_request_delta") or 0),
        "toolCallDelta": int(row.get("tool_call_delta") or 0),
    }


def _serialize_workflow_roi_quality(quality: object) -> dict:
    row = quality if isinstance(quality, dict) else {}
    return {
        "status": row.get("status") or "not_measured",
        "current": _serialize_workflow_roi_quality_bucket(row.get("current")),
        "baseline": _serialize_workflow_roi_quality_bucket(row.get("baseline")),
    }


def _serialize_workflow_roi_quality_bucket(bucket: object) -> dict:
    row = bucket if isinstance(bucket, dict) else {}
    return {
        "runCount": int(row.get("run_count") or 0),
        "passedCount": int(row.get("passed_count") or 0),
        "failedCount": int(row.get("failed_count") or 0),
        "passRate": float(row.get("pass_rate") or 0),
    }
def _serialize_budget_policy(policy: BudgetPolicy) -> dict:
    return {
        "id": policy.id,
        "name": policy.name or "",
        "userId": policy.user_id or "",
        "projectId": policy.project_id or "",
        "dailyRequestLimit": int(policy.daily_request_limit) if policy.daily_request_limit is not None else None,
        "dailyTokenLimit": int(policy.daily_token_limit) if policy.daily_token_limit is not None else None,
        "dailyCostLimit": float(policy.daily_cost_limit) if policy.daily_cost_limit is not None else None,
        "warnAtPercent": int(policy.warn_at_percent or 80),
        "blockAtPercent": int(policy.block_at_percent or 100),
        "isActive": bool(policy.is_active),
        "createdAt": _serialize_timestamp(policy.created_at),
        "updatedAt": _serialize_timestamp(policy.updated_at),
    }


def _serialize_exec_policy_config(config: ExecPolicyConfig) -> dict:
    project = getattr(config, "project", None)
    return {
        "id": config.id,
        "name": config.name or "",
        "projectId": config.project_id or "",
        "projectName": project.name if project else "",
        "priority": int(config.priority or 0),
        "isActive": bool(config.is_active),
        "config": normalize_exec_policy_config(config.config_json or {}),
        "createdAt": _serialize_timestamp(config.created_at),
        "updatedAt": _serialize_timestamp(config.updated_at),
    }


def _format_message_runtime_label(provider: str | None, model: str | None) -> str:
    provider_value = (provider or "").strip()
    model_value = (model or "").strip()
    provider_display = "Orchestrator" if provider_value.lower() == "orchestrator" else provider_value
    if provider_value and model_value:
        return f"{provider_display} / {model_value}"
    if model_value:
        return model_value
    if provider_value:
        return provider_display
    return ""
