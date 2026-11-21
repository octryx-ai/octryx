"""Generic progress-quality checks for agent loop control."""

from __future__ import annotations

import json
from typing import Any

from ....services.prompt_catalog import render_prompt

_CODING_MUTATION_TOOLS = {
    "apply_patch_workspace",
    "edit_workspace_file",
    "multi_edit_workspace_file",
    "run_openrewrite_recipe",
    "write_workspace_file",
}
_CODING_VALIDATION_TOOLS = {"run_cli_command", "run_test_suite"}
_CODING_REVIEW_DELIVERY_TOOLS = {"commit_and_push_repository_branch", "create_bitbucket_pull_request"}
_BLOCKER_TOOLS = {"ask_clarification"}


def detect_unsupported_no_tool_progress_claim(
    *,
    assistant_content: str,
    history: list[dict[str, Any]] | None,
    is_governed: bool,
) -> dict[str, Any] | None:
    """State-based premature-finalization guard for governed coding runs.

    Decides from the turn's executed-tool history, never from prose: in a
    governed run, ANY no-tool answer before the required evidence exists
    (mutation + validation + delivery, or an explicit blocker) is premature —
    regardless of how the claim is phrased or in which language. ``is_governed``
    is the explicit signal: the workflow contract carries the approved verification
    contract (``is_governed_coding_contract``).
    """
    if not is_governed:
        return None
    content = str(assistant_content or "").strip()
    if not content:
        return None
    successful_tool_names = _successful_tool_names(history)
    has_mutation = bool(successful_tool_names.intersection(_CODING_MUTATION_TOOLS))
    has_validation = _has_successful_validation(history)
    has_delivery = bool(successful_tool_names.intersection(_CODING_REVIEW_DELIVERY_TOOLS))
    has_blocker = bool(successful_tool_names.intersection(_BLOCKER_TOOLS))

    if has_blocker or (has_mutation and has_validation and has_delivery):
        return None
    missing = _completion_missing_evidence(
        has_mutation=has_mutation,
        has_validation=has_validation,
        has_delivery=has_delivery,
    )
    return _unsupported_claim_event(
        claim="completion",
        missing=missing,
        next_action=render_prompt("guard.progress.completion_next_action"),
    )


def detect_tool_activity_stall(
    *,
    history: list[dict[str, Any]] | None,
    activity_tool_names: set[str],
    productive_tool_names: set[str],
    limit: int,
    hard_limit: int | None = None,
) -> dict[str, Any] | None:
    successful = _successful_tool_items(history)
    if any(str(item.get("tool_name") or "").strip() in productive_tool_names for item in successful):
        return None
    activity_items = [
        item for item in successful if str(item.get("tool_name") or "").strip() in activity_tool_names
    ]
    activity_count = len(activity_items)
    effective_limit = max(1, int(limit or 1))
    effective_hard_limit = max(effective_limit + 1, int(hard_limit or effective_limit * 2))
    if activity_count < effective_limit:
        return None
    if activity_count != effective_limit and activity_count < effective_hard_limit:
        return None
    counts: dict[str, int] = {}
    for item in activity_items:
        tool_name = str(item.get("tool_name") or "").strip()
        counts[tool_name] = counts.get(tool_name, 0) + 1
    return {
        "kind": "tool_activity_stall",
        "action": "force_next_productive_action" if activity_count < effective_hard_limit else "stop_with_blocker",
        "activity_tool_calls": activity_count,
        "limit": effective_limit,
        "hard_limit": effective_hard_limit,
        "hard_stop": activity_count >= effective_hard_limit,
        "tool_counts": counts,
        "message": (
            "The run keeps collecting activity evidence without producing a productive action. "
            "Reuse gathered evidence and move to the next state action or stop with a concrete blocker."
        ),
    }


def duplicate_read_only_progress_event(*, tool_name: str, tool_args: dict[str, Any]) -> dict[str, Any]:
    return {
        "kind": "duplicate_read_only_tool_call",
        "action": "reuse_prior_evidence",
        "tool_name": tool_name,
        "tool_args_signature": json.dumps(tool_args or {}, sort_keys=True, separators=(",", ":"), default=str),
        "message": render_prompt("guard.progress.duplicate_read_only"),
    }


def _successful_tool_items(history: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    successful: list[dict[str, Any]] = []
    for item in history or []:
        if not isinstance(item, dict):
            continue
        result = item.get("result")
        if isinstance(result, dict) and result.get("error"):
            continue
        successful.append(item)
    return successful


def _successful_tool_names(history: list[dict[str, Any]] | None) -> set[str]:
    return {str(item.get("tool_name") or "").strip() for item in _successful_tool_items(history)}


def _has_successful_validation(history: list[dict[str, Any]] | None) -> bool:
    for item in _successful_tool_items(history):
        tool_name = str(item.get("tool_name") or "").strip()
        result = item.get("result") if isinstance(item.get("result"), dict) else {}
        outcome = result.get("validation_outcome") if isinstance(result.get("validation_outcome"), dict) else None
        if outcome is not None:
            if str(outcome.get("status") or "").strip() == "passed":
                return True
            continue
        if tool_name == "run_test_suite":
            exit_code = result.get("exit_code") if isinstance(result.get("exit_code"), int) else None
            if result.get("all_green") is False or (exit_code is not None and exit_code != 0):
                continue
            return True
        if tool_name != "run_cli_command":
            continue
        command = str(result.get("command") or "").strip()
        params = item.get("parameters") if isinstance(item.get("parameters"), dict) else {}
        command = command or str(params.get("command") or "").strip()
        exit_code = result.get("exit_code") if isinstance(result.get("exit_code"), int) else None
        if command and (exit_code is None or exit_code == 0):
            return True
    return False


def _unsupported_claim_event(*, claim: str, missing: str, next_action: str) -> dict[str, Any]:
    return {
        "kind": "unsupported_no_tool_progress_claim",
        "claim": claim,
        "missing_evidence": missing,
        "action": "require_tool_evidence_or_blocker",
        "message": render_prompt("guard.progress.unsupported_claim", claim=claim, missing=missing, next_action=next_action),
    }


def _completion_missing_evidence(*, has_mutation: bool, has_validation: bool, has_delivery: bool) -> str:
    missing = []
    if not has_mutation:
        missing.append(render_prompt("guard.progress.missing_mutation"))
    if not has_validation:
        missing.append(render_prompt("guard.progress.missing_validation"))
    if not has_delivery:
        missing.append(render_prompt("guard.progress.missing_delivery"))
    return ", ".join(missing) or render_prompt("guard.progress.missing_default")
