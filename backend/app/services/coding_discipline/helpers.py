from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from typing import Any

from ...models import TurnTrace

CODE_INTELLIGENCE_TOOLS = {
    "analyze_workspace_repository",
    "analyze_codebase_patterns",
    "code_search",
    "code_symbol_definition",
    "code_references",
    "code_callers",
    "code_callees",
    "code_file_outline",
    "code_files",
    "code_context",
    "code_explore",
    "code_trace",
    "code_impact",
    "code_impact_analysis",
    "code_graph_status",
    "code_graph_summary",
}
QUALITY_TOOLS = {
    "run_test_suite",
    "lint_and_format_workspace",
    "run_sast_suite",
    "run_openrewrite_recipe",
    "self_review_workspace_diff",
    "build_pull_request_description",
}
TEST_TOOLS = {"run_test_suite"}
FORMAT_TOOLS = {"lint_and_format_workspace", "run_openrewrite_recipe"}
REVIEW_TOOLS = {"self_review_workspace_diff", "run_sast_suite", "build_pull_request_description"}


def _coerce_utc_bounds(*, date_from: date | None, date_to: date | None) -> tuple[datetime | None, datetime | None]:
    start = datetime.combine(date_from, time.min, tzinfo=UTC) if date_from else None
    end = datetime.combine(date_to + timedelta(days=1), time.min, tzinfo=UTC) if date_to else None
    return start, end


def _coerce_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _coerce_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _coerce_float(value: Any) -> float | None:
    if value is None or value == "" or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _tool_trace_items(trace: TurnTrace) -> list[dict[str, Any]]:
    return [item for item in _coerce_list(trace.tool_trace_json) if isinstance(item, dict)]


def _extract_successful_attempt(
    raw_output: dict[str, Any], *, provider_name: str, model_id: str
) -> dict[str, Any] | None:
    attempts = [item for item in _coerce_list(raw_output.get("runtime_attempts")) if isinstance(item, dict)]
    matching = [
        item
        for item in attempts
        if item.get("status") == "success"
        and not item.get("empty_assistant_output")
        and (not provider_name or str(item.get("provider") or "").strip() == provider_name)
        and (not model_id or str(item.get("model") or "").strip() == model_id)
    ]
    if matching:
        return matching[-1]
    successful = [
        item for item in attempts if item.get("status") == "success" and not item.get("empty_assistant_output")
    ]
    return successful[-1] if successful else None


def _coding_discipline_for_trace(trace: TurnTrace) -> str:
    context = _coerce_dict(trace.context_snapshot_json)
    tool_trace = _tool_trace_items(trace)
    tool_names = {
        str(item.get("tool_name") or "").strip().lower()
        for item in tool_trace
        if str(item.get("tool_name") or "").strip()
    }
    subtask_role = str(context.get("subtask_model_role") or "").strip().lower()
    reasoning_stage = str(context.get("reasoning_stage") or "").strip().lower()
    reasoning_task_type = str(context.get("reasoning_task_type") or "").strip().lower()

    if subtask_role in {"self_review", "security_review", "pr_description"} or reasoning_stage == "verifier":
        return "review"
    if subtask_role in {"test_generation"}:
        return "test-fix"
    if subtask_role in {"code_generation", "lint_fix"}:
        return "edit"
    if reasoning_task_type == "review":
        return "review"
    if tool_names & CODE_INTELLIGENCE_TOOLS:
        if tool_names & (TEST_TOOLS | FORMAT_TOOLS):
            return "edit"
        return "repo-intelligence"
    if reasoning_stage == "planner":
        return "planning"
    return "planning"


def _quality_signal_for_trace(trace: TurnTrace) -> tuple[bool, bool]:
    tool_trace = _tool_trace_items(trace)
    quality_seen = False
    quality_passed = False
    for item in tool_trace:
        tool_name = str(item.get("tool_name") or "").strip().lower()
        if tool_name not in QUALITY_TOOLS:
            continue
        quality_seen = True
        result = _coerce_dict(item.get("result"))
        status = str(item.get("status") or result.get("status") or "").strip().lower()
        if tool_name == "self_review_workspace_diff":
            quality_passed = quality_passed or bool(result.get("ready_for_pr"))
        elif status in {"success", "completed", "ready"} or result.get("ok") is True:
            quality_passed = True
    return quality_seen, quality_passed


def _tool_status_succeeded(item: dict[str, Any]) -> bool:
    result = _coerce_dict(item.get("result"))
    status = str(item.get("status") or result.get("status") or "").strip().lower()
    if status in {"success", "completed", "ready", "passed", "ok"}:
        return True
    if result.get("ok") is True:
        return True
    if result.get("success") is True:
        return True
    return False


def _verification_metrics_for_trace(trace: TurnTrace) -> dict[str, Any]:
    tool_trace = _tool_trace_items(trace)
    code_intelligence_calls = 0
    quality_calls = 0
    tests_seen = False
    tests_passed = False
    formatting_seen = False
    formatting_passed = False
    review_seen = False
    review_passed = False

    for item in tool_trace:
        tool_name = str(item.get("tool_name") or "").strip().lower()
        succeeded = _tool_status_succeeded(item)
        result = _coerce_dict(item.get("result"))
        if tool_name in CODE_INTELLIGENCE_TOOLS:
            code_intelligence_calls += 1
        if tool_name in QUALITY_TOOLS:
            quality_calls += 1
        if tool_name in TEST_TOOLS:
            tests_seen = True
            tests_passed = tests_passed or succeeded
        if tool_name in FORMAT_TOOLS:
            formatting_seen = True
            formatting_passed = formatting_passed or succeeded
        if tool_name in REVIEW_TOOLS:
            review_seen = True
            if tool_name == "self_review_workspace_diff":
                review_passed = review_passed or bool(result.get("ready_for_pr"))
            else:
                review_passed = review_passed or succeeded

    verification_seen = tests_seen or formatting_seen or review_seen
    verification_passed = tests_passed or formatting_passed or review_passed
    return {
        "code_intelligence_calls": code_intelligence_calls,
        "quality_calls": quality_calls,
        "tests_seen": tests_seen,
        "tests_passed": tests_passed,
        "formatting_seen": formatting_seen,
        "formatting_passed": formatting_passed,
        "review_seen": review_seen,
        "review_passed": review_passed,
        "verification_seen": verification_seen,
        "verification_passed": verification_passed,
    }


def _productivity_metrics_for_trace(trace: TurnTrace) -> dict[str, Any]:
    raw_output = _coerce_dict(trace.raw_output)
    tool_trace = _tool_trace_items(trace)
    content = str(raw_output.get("content") or "").strip()
    suppressed_as_transitional = bool(raw_output.get("suppressed_as_transitional"))
    runtime_error = str(raw_output.get("error") or "").strip()
    has_tool_work = bool(tool_trace)
    productive = has_tool_work or bool(content and not suppressed_as_transitional and not runtime_error)
    transitional_stall = suppressed_as_transitional and not has_tool_work
    return {
        "productive": productive,
        "transitional_stall": transitional_stall,
        "has_tool_work": has_tool_work,
        "has_visible_content": bool(content and not suppressed_as_transitional),
    }


def _discipline_alignment_score(*, discipline: str, metrics: dict[str, Any]) -> float:
    normalized = str(discipline or "").strip().lower()
    code_intelligence_calls = int(metrics.get("code_intelligence_calls") or 0)
    verification_passed = bool(metrics.get("verification_passed"))
    tests_passed = bool(metrics.get("tests_passed"))
    formatting_passed = bool(metrics.get("formatting_passed"))
    review_passed = bool(metrics.get("review_passed"))

    if normalized == "repo-intelligence":
        return 1.0 if code_intelligence_calls > 0 else 0.0
    if normalized == "planning":
        return 1.0 if code_intelligence_calls > 0 else 0.6
    if normalized == "review":
        return 1.0 if review_passed else (0.7 if bool(metrics.get("review_seen")) else 0.3)
    if normalized == "test-fix":
        if tests_passed and formatting_passed:
            return 1.0
        if tests_passed:
            return 0.85
        if verification_passed:
            return 0.7
        return 0.25
    if normalized == "edit":
        if tests_passed and formatting_passed:
            return 1.0
        if verification_passed:
            return 0.8
        if code_intelligence_calls > 0:
            return 0.55
        return 0.2
    return 0.5



def _mean(values: list[float]) -> float | None:
    return float(sum(values) / len(values)) if values else None


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    rank = (len(ordered) - 1) * max(0.0, min(1.0, percentile))
    lower = int(rank)
    upper = min(lower + 1, len(ordered) - 1)
    if lower == upper:
        return float(ordered[lower])
    weight = rank - lower
    return float(ordered[lower] + (ordered[upper] - ordered[lower]) * weight)
