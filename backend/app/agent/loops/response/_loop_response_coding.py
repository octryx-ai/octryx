"""Coding and required-tool response guards for the standard loop."""

from __future__ import annotations

import re
from typing import Any

from ....services.response_guard_policy import (
    CLARIFICATION_BLOCKER_PATTERN,
    CLARIFICATION_MARKER_PATTERN,
    CLARIFICATION_QUESTION_PATTERN,
)
from ._loop_coding_guard_nudges import (
    GOVERNED_WITHOUT_DELIVERY_NUDGE,
    INTENT_ONLY_NUDGE,
    NO_EXECUTION_NUDGE,
    CodingGuardInputs,
    CodingNudge,
    guard_counts,
    nudge_coding_reply,
)
from ._loop_response_step_tools import handle_required_tool_step_response

# A knowledge workflow answers a question - it must never be treated as a coding turn even if the
# capability mode is "change": its answer may mention pipeline "steps" without being coding progress.
_KNOWLEDGE_EVIDENCE_WORKFLOWS = frozenset({"knowledge_request"})


def _is_knowledge_evidence_turn(context_snapshot: dict[str, Any]) -> bool:
    request_analysis = context_snapshot.get("request_analysis") if isinstance(context_snapshot, dict) else None
    contract = request_analysis.get("workflow_contract") if isinstance(request_analysis, dict) else None
    workflow_id = str((contract or {}).get("workflow_id") or "").strip() if isinstance(contract, dict) else ""
    return workflow_id in _KNOWLEDGE_EVIDENCE_WORKFLOWS

_CODING_DELIVERY_TOOL_NAMES = {
    "write_workspace_file",
    "edit_workspace_file",
    "multi_edit_workspace_file",
    "apply_patch_workspace",
    "run_openrewrite_recipe",
    "commit_and_push_repository_branch",
    "create_bitbucket_pull_request",
}
_CODING_VALIDATION_TOOL_NAMES = {
    "run_test_suite",
    "lint_and_format_workspace",
    "self_review_workspace_diff",
    "run_sast_suite",
    "run_cli_command",
    "bash",
}
_BLOCKER_OR_NOOP_PATTERN = re.compile(
    r"\b("
    r"blocked|blocker|cannot safely|not safe|needs human|needs approval|needs clarification|"
    r"source changed|requires re-?planning|no code change(?:s)? (?:is|are) required|"
    r"no repository change(?:s)? (?:is|are) required"
    r")\b",
    re.IGNORECASE,
)


def _looks_like_focused_coding_clarification(content: str) -> bool:
    normalized = str(content or "")
    if len(normalized.strip()) < 160:
        return False
    if not CLARIFICATION_QUESTION_PATTERN.search(normalized):
        return False
    if not CLARIFICATION_MARKER_PATTERN.search(normalized):
        return False
    return bool(CLARIFICATION_BLOCKER_PATTERN.search(normalized))


def _looks_like_sub_agent_resume_prompt(content: str) -> bool:
    normalized = str(content or "").lower()
    return "sub-agent" in normalized or "sub agent" in normalized or "subagents" in normalized


def _has_governed_coding_delivery(tool_history: list[dict[str, Any]] | None) -> bool:
    saw_validation = False
    for item in tool_history or []:
        if not isinstance(item, dict):
            continue
        result = item.get("result")
        if isinstance(result, dict) and result.get("error"):
            continue
        tool_name = str(item.get("tool_name") or "").strip()
        if tool_name in _CODING_DELIVERY_TOOL_NAMES:
            return True
        if tool_name in _CODING_VALIDATION_TOOL_NAMES:
            saw_validation = True
    return saw_validation and any(
        str((item or {}).get("tool_name") or "").strip() in _CODING_DELIVERY_TOOL_NAMES
        for item in tool_history or []
        if isinstance(item, dict)
    )


def _looks_like_explicit_coding_blocker_or_noop(content: str) -> bool:
    normalized = str(content or "")
    return bool(_BLOCKER_OR_NOOP_PATTERN.search(normalized))


def _is_coding_turn(inputs: CodingGuardInputs) -> bool:
    is_coding_request = inputs._is_probable_coding_change_request(
        capability_type=inputs.capability_type,
        user_message=inputs.current_turn_content,
        workspace_root=str(inputs.tool_context.workspace_root),
    )
    # A knowledge/evidence workflow is never a coding turn, even if the capability
    # mode resolved to "change" - otherwise the coding-progress guard kills a
    # legitimate knowledge answer that happens to mention "steps".
    if is_coding_request and _is_knowledge_evidence_turn(inputs.context_snapshot):
        is_coding_request = False
    return is_coding_request


def _coding_nudge_for(inputs: CodingGuardInputs) -> CodingNudge | None:
    """The guard a final coding reply without a step trips, or None (callers checked the shared conditions)."""
    content = inputs.content
    allows_noop = inputs.allows_noop_step_completion
    if (
        not inputs._has_meaningful_coding_execution(inputs.turn_tool_history)
        and not inputs._looks_like_coding_intent_only_response(content)
        and not allows_noop(inputs.current_step, content or "")
    ):
        return NO_EXECUTION_NUDGE
    if (
        inputs.governed_coding
        and not _has_governed_coding_delivery(inputs.turn_tool_history)
        and not _looks_like_explicit_coding_blocker_or_noop(content)
        and not allows_noop(inputs.current_step, content or "")
    ):
        return GOVERNED_WITHOUT_DELIVERY_NUDGE
    if (
        # A run phase whose required tool evidence this turn already produced is reporting, not narrating.
        not inputs.phase_tool_evidence_present
        and inputs._looks_like_coding_intent_only_response(content)
        and not allows_noop(inputs.current_step, content or "")
    ):
        return INTENT_ONLY_NUDGE
    return None


async def handle_coding_response_guards(inputs: CodingGuardInputs) -> dict[str, Any]:
    step_outcome = await handle_required_tool_step_response(inputs)
    if step_outcome is not None:
        return step_outcome
    is_coding_request = _is_coding_turn(inputs)
    prior_turn_tool_names = [
        str((item or {}).get("tool_name") or "").strip()
        for item in (inputs.turn_tool_history or [])
        if isinstance(item, dict)
    ]
    if inputs.current_step is not None or inputs.tool_calls or not is_coding_request:
        return {"action": "none", **guard_counts(inputs)}
    if _looks_like_sub_agent_resume_prompt(inputs.current_turn_content):
        return {"action": "none", **guard_counts(inputs)}
    if _looks_like_focused_coding_clarification(inputs.content) and not inputs.allows_noop_step_completion(
        inputs.current_step, inputs.content or ""
    ):
        return {"action": "none", **guard_counts(inputs)}
    nudge = _coding_nudge_for(inputs)
    if nudge is None:
        return {"action": "none", **guard_counts(inputs)}
    return await nudge_coding_reply(inputs, nudge, prior_turn_tool_names)
