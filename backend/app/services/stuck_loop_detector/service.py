"""Dedicated stuck-loop detection helpers for agent turns."""

from __future__ import annotations

from typing import Any

from ..prompt_catalog import render_prompt

DEFAULT_STUCK_LOOP_TOOL_REPEAT_THRESHOLD = 5
DEFAULT_STUCK_LOOP_BLOCKED_TOOL_THRESHOLD = 2
DEFAULT_STUCK_LOOP_EMPTY_SEARCH_THRESHOLD = 2
DEFAULT_STUCK_LOOP_REPEATED_JIRA_THRESHOLD = 4
DEFAULT_STUCK_LOOP_NO_TOOL_DUPLICATE_THRESHOLD = 2
DEFAULT_STUCK_LOOP_SUMMARY_REPEAT_THRESHOLD = 1
DEFAULT_STUCK_LOOP_NO_TOOL_SIMILARITY_THRESHOLD = 0.72
DEFAULT_STUCK_LOOP_SAME_TARGET_THRESHOLD = 3
META_TOOL_REPEAT_THRESHOLD = 3


def _bounded_int(raw_value: Any, *, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(raw_value)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(parsed, maximum))


def _bounded_float(raw_value: Any, *, default: float, minimum: float, maximum: float) -> float:
    try:
        parsed = float(raw_value)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(parsed, maximum))


def get_stuck_loop_detector_settings(runtime_settings: dict[str, Any] | None = None) -> dict[str, Any]:
    settings = runtime_settings or {}
    return {
        "tool_repeat_threshold": _bounded_int(
            settings.get("stuck_loop_tool_repeat_threshold"),
            default=DEFAULT_STUCK_LOOP_TOOL_REPEAT_THRESHOLD,
            minimum=3,
            maximum=12,
        ),
        "blocked_tool_threshold": _bounded_int(
            settings.get("stuck_loop_blocked_tool_threshold"),
            default=DEFAULT_STUCK_LOOP_BLOCKED_TOOL_THRESHOLD,
            minimum=1,
            maximum=6,
        ),
        "empty_search_threshold": _bounded_int(
            settings.get("stuck_loop_empty_search_threshold"),
            default=DEFAULT_STUCK_LOOP_EMPTY_SEARCH_THRESHOLD,
            minimum=2,
            maximum=6,
        ),
        "repeated_jira_threshold": _bounded_int(
            settings.get("stuck_loop_repeated_jira_threshold"),
            default=DEFAULT_STUCK_LOOP_REPEATED_JIRA_THRESHOLD,
            minimum=2,
            maximum=10,
        ),
        "no_tool_duplicate_threshold": _bounded_int(
            settings.get("stuck_loop_no_tool_duplicate_threshold"),
            default=DEFAULT_STUCK_LOOP_NO_TOOL_DUPLICATE_THRESHOLD,
            minimum=2,
            maximum=6,
        ),
        "summary_repeat_threshold": _bounded_int(
            settings.get("stuck_loop_summary_repeat_threshold"),
            default=DEFAULT_STUCK_LOOP_SUMMARY_REPEAT_THRESHOLD,
            minimum=1,
            maximum=4,
        ),
        "same_target_threshold": _bounded_int(
            settings.get("stuck_loop_same_target_threshold"),
            default=DEFAULT_STUCK_LOOP_SAME_TARGET_THRESHOLD,
            minimum=2,
            maximum=6,
        ),
        "no_tool_similarity_threshold": _bounded_float(
            settings.get("stuck_loop_no_tool_similarity_threshold"),
            default=DEFAULT_STUCK_LOOP_NO_TOOL_SIMILARITY_THRESHOLD,
            minimum=0.5,
            maximum=0.99,
        ),
    }


def _build_event(
    *,
    kind: str,
    message: str,
    step: dict[str, Any] | None,
    step_index: int | None = None,
    severity: str = "warning",
    signal_count: int = 0,
    recommended_action: str = "",
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    step_name = str((step or {}).get("name") or "").strip() or "current step"
    payload = {
        "status": "detected",
        "kind": kind,
        "severity": severity,
        "step_name": step_name,
        "step_index": int(step_index or 0),
        "signal_count": max(0, int(signal_count or 0)),
        "message": message,
        "recommended_action": recommended_action or "force_wrapup",
        "details": details or {},
    }
    return payload


def _history_target(item: dict[str, Any]) -> tuple[str, str]:
    tool_name = str(item.get("tool_name") or "").strip()
    params = item.get("params") if isinstance(item.get("params"), dict) else {}
    result = item.get("result") if isinstance(item.get("result"), dict) else {}
    target = ""
    for key in (
        "knowledge_id",
        "evidence_key",
        "id",
        "key",
        "page_id",
        "artifact_id",
        "path",
        "query",
        "cql",
        "url",
        "repo_slug",
        "file_path",
        "command",
        "cwd",
    ):
        value = str(params.get(key) or "").strip()
        if value:
            target = value
            break
    if not target and result.get("error"):
        target = str(result.get("error") or "").strip()
    return tool_name, target


def _is_empty_search_result(item: dict[str, Any]) -> bool:
    if str(item.get("tool_name") or "").strip() != "web_search":
        return False
    result = item.get("result") if isinstance(item.get("result"), dict) else {}
    if not isinstance(result, dict) or result.get("error"):
        return False
    if isinstance(result.get("items"), list) and result.get("items"):
        return False
    try:
        count = int(result.get("count"))
    except (TypeError, ValueError):
        count = 0 if isinstance(result.get("items"), list) else -1
    return count == 0


def detect_tool_stuck_loop(
    *,
    step: dict[str, Any] | None,
    history: list[dict[str, Any]],
    step_index: int | None = None,
    runtime_settings: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    if not history:
        return None
    settings = get_stuck_loop_detector_settings(runtime_settings)
    step_name = str((step or {}).get("name") or "").strip() or "current step"
    step_type = str((step or {}).get("stepType") or (step or {}).get("step_type") or "").strip().lower()
    recent_history = history[-6:]
    recent_tool_names = [str(item.get("tool_name") or "").strip() for item in recent_history]
    same_target_threshold = settings["same_target_threshold"]
    recent_targets = [_history_target(item) for item in history[-8:]]
    if recent_targets:
        repeated_target = recent_targets[-1]
        if repeated_target[0] and repeated_target[1]:
            repeated_count = sum(1 for item in recent_targets if item == repeated_target)
            if repeated_count >= same_target_threshold:
                return _build_event(
                    kind="repeated_same_target_loop",
                    message=render_prompt(
                        "tool_guard.stuck_loop.repeated_same_target_loop",
                        step_name=step_name,
                        target_tool=repeated_target[0],
                    ),
                    step=step,
                    step_index=step_index,
                    signal_count=repeated_count,
                    recommended_action="move_or_wrapup",
                    details={
                        "tool_name": repeated_target[0],
                        "target": repeated_target[1],
                        "recent_targets": recent_targets,
                    },
                )

    knowledge_cycle_threshold = max(same_target_threshold * 2, 6)
    if len(recent_targets) >= knowledge_cycle_threshold:
        lookup_targets = [
            target
            for target in recent_targets
            if target[0] in {"knowledge_read", "knowledge_search", "search_confluence"}
            and target[1]
        ]
        if len(lookup_targets) >= knowledge_cycle_threshold:
            unique_tools = {tool_name for tool_name, _target in lookup_targets}
            unique_targets = {_target for _tool_name, _target in lookup_targets}
            if len(unique_tools) <= 3 and len(unique_targets) <= 3:
                return _build_event(
                    kind="repetitive_knowledge_lookup_loop",
                    message=render_prompt(
                        "tool_guard.stuck_loop.repetitive_knowledge_lookup_loop", step_name=step_name
                    ),
                    step=step,
                    step_index=step_index,
                    signal_count=len(lookup_targets),
                    recommended_action="move_or_wrapup",
                    details={
                        "tools": sorted(unique_tools),
                        "targets": sorted(unique_targets),
                        "recent_targets": recent_targets,
                    },
                )

    evidence_cycle_targets = [
        target
        for target in recent_targets
        if target[0]
        in {
            "analyze_workspace_repository",
            "bash",
            "code_search",
            "grep_workspace",
            "list_workspace_directory",
            "prepare_bitbucket_repository",
            "read_workspace_file",
        }
        and target[1]
    ]
    if len(evidence_cycle_targets) >= 6:
        unique_tools = {tool_name for tool_name, _target in evidence_cycle_targets}
        unique_targets = {_target for _tool_name, _target in evidence_cycle_targets}
        repeated_target_count = max(
            (
                sum(1 for item in evidence_cycle_targets if item == candidate)
                for candidate in set(evidence_cycle_targets)
            ),
            default=0,
        )
        if len(unique_tools) <= 6 and len(unique_targets) <= 8 and repeated_target_count >= 2:
            return _build_event(
                kind="repetitive_evidence_target_cycle",
                message=render_prompt("tool_guard.stuck_loop.repetitive_evidence_target_cycle", step_name=step_name),
                step=step,
                step_index=step_index,
                signal_count=len(evidence_cycle_targets),
                recommended_action="move_or_wrapup",
                details={
                    "tools": sorted(unique_tools),
                    "targets": sorted(unique_targets),
                    "recent_targets": recent_targets,
                },
            )

    repeat_threshold = settings["tool_repeat_threshold"]
    repeat_slice = recent_tool_names[-repeat_threshold:]
    error_repeat_threshold = settings["blocked_tool_threshold"]
    error_slice = recent_history[-error_repeat_threshold:]
    if len(error_slice) >= error_repeat_threshold:
        error_tool_names = [str(item.get("tool_name") or "").strip() for item in error_slice]
        error_texts = []
        for item in error_slice:
            result = item.get("result") if isinstance(item.get("result"), dict) else {}
            error_texts.append(str(result.get("error") or "").strip())
        repeated_error_tool = error_tool_names[-1] if error_tool_names else ""
        if (
            repeated_error_tool
            and len(set(error_tool_names)) == 1
            and all(error_texts)
        ):
            return _build_event(
                kind="repetitive_tool_error_loop",
                message=render_prompt(
                    "tool_guard.stuck_loop.repetitive_tool_error_loop",
                    step_name=step_name,
                    repeated_error_tool=repeated_error_tool,
                ),
                step=step,
                step_index=step_index,
                signal_count=len(error_slice),
                recommended_action="move_or_wrapup",
                details={"tool_name": repeated_error_tool, "errors": error_texts},
            )
    empty_search_threshold = settings["empty_search_threshold"]
    empty_search_slice = recent_history[-empty_search_threshold:]
    if len(empty_search_slice) >= empty_search_threshold and all(
        _is_empty_search_result(item) for item in empty_search_slice
    ):
        return _build_event(
            kind="repetitive_empty_search_loop",
            message=render_prompt("tool_guard.stuck_loop.repetitive_empty_search_loop", step_name=step_name),
            step=step,
            step_index=step_index,
            signal_count=len(empty_search_slice),
            recommended_action="move_or_wrapup",
            details={"tool_name": "web_search", "empty_results": len(empty_search_slice)},
        )
    if len(repeat_slice) >= repeat_threshold and len(set(repeat_slice)) == 1:
        repeated_tool = repeat_slice[-1]
        return _build_event(
            kind="repetitive_tool_loop",
            message=render_prompt(
                "tool_guard.stuck_loop.repetitive_tool_loop", step_name=step_name, repeated_tool=repeated_tool
            ),
            step=step,
            step_index=step_index,
            signal_count=len(repeat_slice),
            recommended_action="move_or_wrapup",
            details={"tool_name": repeated_tool, "recent_tool_names": recent_tool_names[-repeat_threshold:]},
        )

    meta_repeat_slice = recent_tool_names[-META_TOOL_REPEAT_THRESHOLD:]
    if len(meta_repeat_slice) >= META_TOOL_REPEAT_THRESHOLD and len(set(meta_repeat_slice)) == 1:
        repeated_tool = meta_repeat_slice[-1]
        if repeated_tool in {"load_tool_artifact"}:
            return _build_event(
                kind="repetitive_meta_tool_loop",
                message=render_prompt(
                    "tool_guard.stuck_loop.repetitive_meta_tool_loop", step_name=step_name, repeated_tool=repeated_tool
                ),
                step=step,
                step_index=step_index,
                signal_count=len(meta_repeat_slice),
                recommended_action="move_or_wrapup",
                details={
                    "tool_name": repeated_tool,
                    "recent_tool_names": recent_tool_names[-META_TOOL_REPEAT_THRESHOLD:],
                },
            )

    blocked_attempts = 0
    for item in recent_history:
        result = item.get("result")
        if isinstance(result, dict):
            error_text = str(result.get("error") or "").lower()
            if "not allowed in the current step" in error_text:
                blocked_attempts += 1
    if blocked_attempts >= settings["blocked_tool_threshold"]:
        return _build_event(
            kind="out_of_contract_tool_loop",
            message=render_prompt("tool_guard.stuck_loop.out_of_contract_tool_loop", step_name=step_name),
            step=step,
            step_index=step_index,
            signal_count=blocked_attempts,
            recommended_action="move_or_wrapup",
            details={"blocked_attempts": blocked_attempts},
        )

    if step_type == "analysis":
        repo_evidence_tools = {
            "prepare_bitbucket_repository",
            "git_change_summary",
            "analyze_workspace_repository",
            "list_workspace_git_commits",
        }
        repo_evidence_collected = any(
            str(item.get("tool_name") or "").strip() in repo_evidence_tools for item in history
        )
        repeated_jira_searches = sum(
            1 for item in recent_history if str(item.get("tool_name") or "").strip() == "search_jira_tickets"
        )
        if repo_evidence_collected and repeated_jira_searches >= settings["repeated_jira_threshold"]:
            return _build_event(
                kind="expanding_search_loop",
                message=render_prompt("tool_guard.stuck_loop.expanding_search_loop", step_name=step_name),
                step=step,
                step_index=step_index,
                signal_count=repeated_jira_searches,
                recommended_action="move_or_wrapup",
                details={"tool_name": "search_jira_tickets", "repeated_searches": repeated_jira_searches},
            )
    return None


def detect_no_tool_stuck_loop(
    *,
    step: dict[str, Any] | None,
    step_index: int | None,
    current_content: str,
    current_signature: str | None,
    previous_content: str,
    previous_signature: str | None,
    similarity: float,
    duplicate_count: int,
    repeated_previous_step_summary_count: int,
    repeated_previous_step_summary: bool,
    runtime_settings: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    settings = get_stuck_loop_detector_settings(runtime_settings)
    step_name = str((step or {}).get("name") or "").strip() or "current step"
    if repeated_previous_step_summary and repeated_previous_step_summary_count >= settings["summary_repeat_threshold"]:
        return _build_event(
            kind="repeated_previous_step_summary",
            message=render_prompt("tool_guard.stuck_loop.repeated_previous_step_summary", step_name=step_name),
            step=step,
            step_index=step_index,
            signal_count=repeated_previous_step_summary_count,
            recommended_action="continue_current_step",
            details={"similarity": round(similarity, 4), "content": current_content[:240]},
        )
    if (
        current_signature
        and previous_signature
        and current_signature == previous_signature
        and duplicate_count >= settings["no_tool_duplicate_threshold"]
        and similarity >= settings["no_tool_similarity_threshold"]
    ):
        return _build_event(
            kind="duplicate_no_tool_response",
            message=render_prompt("tool_guard.stuck_loop.duplicate_no_tool_response", step_name=step_name),
            step=step,
            step_index=step_index,
            signal_count=duplicate_count,
            recommended_action="stop_or_recover",
            details={
                "signature": current_signature,
                "similarity": round(similarity, 4),
                "current_excerpt": current_content[:240],
                "previous_excerpt": previous_content[:240],
            },
        )
    return None


def build_iteration_ceiling_event(
    *,
    step: dict[str, Any] | None,
    step_index: int | None,
    attempts_used: int,
    max_iterations: int,
) -> dict[str, Any]:
    step_name = str((step or {}).get("name") or "").strip() or "current step"
    return _build_event(
        kind="iteration_ceiling",
        message=render_prompt(
            "tool_guard.stuck_loop.iteration_ceiling",
            step_name=step_name,
            attempts_used=attempts_used,
            max_iterations=max_iterations,
        ),
        step=step,
        step_index=step_index,
        severity="error",
        signal_count=attempts_used,
        recommended_action="move_or_wrapup",
        details={"attempts_used": attempts_used, "max_iterations": max_iterations},
    )
