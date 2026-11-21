"""Policy helpers for turn-level tool execution.

Service-owned module: turn-level tool guards (coding intelligence prewrite,
clarification gate, custom exec-policy guards, tool name sanitization). Moved
from ``app.agent.engine._turn_tools_policy``; AWS-specific guards live in
``app.services.turn_tool_guards_aws`` and the technical source credibility
guard in ``app.services.turn_tool_guards_research``.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from ..agent.runtime_defaults import (
    CODE_DIRECTORY_TOKENS,
    CODE_FILE_NAMES,
    CODE_FILE_SUFFIXES,
    CODING_INTELLIGENCE_TOOLS,
    CODING_WRITE_TOOLS,
    DEFAULT_AGENT_MODE_KEY,
    SUMMARY_DOMAIN_FALLBACK_TOOLS,
)
from ..tools.registry import get_all_tools_with_plugins
from ..tools.tool_names import ToolName
from .exec_policy import (
    agent_guard_rule,
    apply_agent_guard_metadata,
    custom_tool_guard_decisions,
    custom_tool_guard_result,
)
from .prompt_catalog import render_prompt

_TOOL_NAME_TOKEN_PATTERN = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def _active_guard_rule(exec_policy_config: dict[str, Any] | None, guard_id: str) -> dict[str, Any] | None:
    rule = agent_guard_rule(exec_policy_config, guard_id)
    if not bool(rule.get("enabled", True)):
        return None
    return rule


def _guard_result(result: dict[str, Any], rule: dict[str, Any]) -> dict[str, Any]:
    return apply_agent_guard_metadata(result, rule)


def custom_exec_policy_tool_guard_result(
    *,
    tool_name: str,
    tool_args: dict[str, Any],
    capability_type: str | None,
    exec_policy_config: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    return custom_tool_guard_result(
        exec_policy_config,
        tool_name=tool_name,
        tool_args=tool_args,
        capability_type=capability_type,
    )


def custom_exec_policy_tool_guard_decisions(
    *,
    tool_name: str,
    tool_args: dict[str, Any],
    capability_type: str | None,
    exec_policy_config: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    return custom_tool_guard_decisions(
        exec_policy_config,
        tool_name=tool_name,
        tool_args=tool_args,
        capability_type=capability_type,
    )


def _looks_like_code_artifact_path(raw_path: str) -> bool:
    normalized = str(raw_path or "").strip().replace("\\", "/")
    if not normalized:
        return False
    path = Path(normalized)
    if path.suffix.lower() in CODE_FILE_SUFFIXES:
        return True
    if path.name in CODE_FILE_NAMES:
        return True
    return any(part.lower() in CODE_DIRECTORY_TOKENS for part in path.parts)


def _looks_like_workflow_plan_artifact_path(raw_path: str) -> bool:
    normalized = str(raw_path or "").strip().replace("\\", "/")
    if not normalized:
        return False
    path = Path(normalized)
    return path.name.lower().endswith("_plan.json")


def _extract_patch_paths(patch_text: str) -> list[str]:
    paths: list[str] = []
    for raw_line in str(patch_text or "").splitlines():
        if raw_line.startswith("+++ ") or raw_line.startswith("--- "):
            path = raw_line[4:].strip()
            if path == "/dev/null":
                continue
            if path.startswith("a/") or path.startswith("b/"):
                path = path[2:]
            if path:
                paths.append(path)
    return paths


def _tool_targets_code_artifact(tool_name: str, tool_args: dict[str, Any]) -> bool:
    normalized_tool_name = str(tool_name or "").strip().lower()
    if normalized_tool_name not in CODING_WRITE_TOOLS:
        return False
    if normalized_tool_name == ToolName.APPLY_PATCH_WORKSPACE:
        patch_text = str(tool_args.get("patch") or tool_args.get("patch_text") or "")
        paths = _extract_patch_paths(patch_text)
        return any(_looks_like_code_artifact_path(path) for path in paths)
    raw_path = str(tool_args.get("path") or tool_args.get("file_path") or "").strip()
    if normalized_tool_name == ToolName.WRITE_WORKSPACE_FILE and _looks_like_workflow_plan_artifact_path(raw_path):
        return False
    return _looks_like_code_artifact_path(raw_path)


def coding_intelligence_guard_result(
    *,
    tool_name: str,
    tool_args: dict[str, Any],
    turn_tool_history: list[dict[str, Any]] | None,
    capability_type: str | None,
    exec_policy_config: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    guard_rule = _active_guard_rule(exec_policy_config, "coding_prewrite_intelligence_required")
    if guard_rule is None:
        return None
    if str(capability_type or "").strip().lower() != "change":
        return None
    if not _tool_targets_code_artifact(tool_name, tool_args):
        return None
    prior_tools = {
        str((item or {}).get("tool_name") or "").strip()
        for item in (turn_tool_history or [])
        if isinstance(item, dict)
    }
    if prior_tools & CODING_INTELLIGENCE_TOOLS:
        return None
    return _guard_result({
        "error": render_prompt("tool_guard.coding_prewrite.error", tool_name=tool_name),
        "guardrail": "coding_prewrite_intelligence_required",
        "required_before_write": sorted(CODING_INTELLIGENCE_TOOLS),
        "suggested_next_tools": [
            "analyze_workspace_repository",
            "code_graph_status",
            "code_explore",
            "code_context",
            "code_search",
            "code_impact",
        ],
        "target_path": str(tool_args.get("path") or tool_args.get("file_path") or "").strip(),
        "reason": render_prompt("tool_guard.coding_prewrite.reason"),
    }, guard_rule)


def clarification_gate_guard_result(
    *,
    tool_name: str,
    tool_args: dict[str, Any],
    context_snapshot: dict[str, Any] | None,
    exec_policy_config: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    # Persisted exec-policy overrides name this rule id; the envelope is a
    # platform work item.
    guard_rule = _active_guard_rule(exec_policy_config, "work_package_clarification_required")
    if guard_rule is None:
        return None
    normalized_tool_name = str(tool_name or "").strip().lower()
    if normalized_tool_name not in CODING_WRITE_TOOLS:
        return None
    if not _tool_targets_code_artifact(normalized_tool_name, tool_args):
        return None

    snapshot = context_snapshot or {}
    coding_run = snapshot.get("coding_run") if isinstance(snapshot.get("coding_run"), dict) else {}
    clarification_state = str(coding_run.get("clarification_state") or "").strip().lower()
    clarification = coding_run.get("clarification") if isinstance(coding_run.get("clarification"), dict) else {}
    readiness = str(clarification.get("readiness") or "").strip().lower()
    if clarification_state in {"", "not_required", "resolved"} and readiness in {"", "ready"}:
        return None

    questions = [item for item in clarification.get("questions") or [] if isinstance(item, dict)]
    return _guard_result({
        "error": render_prompt("tool_guard.clarification.error", tool_name=tool_name),
        "guardrail": "work_package_clarification_required",
        "clarification_state": clarification_state or "unknown",
        "readiness": readiness or "unknown",
        "questions": questions,
        "target_path": str(tool_args.get("path") or tool_args.get("file_path") or "").strip(),
        "reason": render_prompt("tool_guard.clarification.reason"),
    }, guard_rule)


def sanitize_tool_name(
    raw_tool_name: Any,
    *,
    allowed_tool_names: set[str] | None = None,
    capability_type: str | None = None,
) -> str:
    normalized = str(raw_tool_name or "").strip()
    if not normalized:
        return ""
    if "<" not in normalized and "\n" not in normalized and "\r" not in normalized:
        return normalized

    candidate_names: set[str] = {str(name).strip() for name in (allowed_tool_names or set()) if str(name).strip()}
    try:
        registry_tools = get_all_tools_with_plugins(capability_type or DEFAULT_AGENT_MODE_KEY)
    except (ImportError, AttributeError, RuntimeError, ValueError, OSError):
        registry_tools = []
    candidate_names.update(
        str(tool.get("function", {}).get("name") or "").strip() for tool in registry_tools if isinstance(tool, dict)
    )
    candidate_names.discard("")

    for token in _TOOL_NAME_TOKEN_PATTERN.findall(normalized):
        if token in candidate_names:
            return token

    prefix = normalized.split("<", 1)[0].strip()
    if prefix in candidate_names:
        return prefix
    return prefix or normalized


def is_required_summary_domain_tool(
    *,
    tool_name: str,
    context_snapshot: dict[str, Any] | None,
) -> bool:
    if not tool_name:
        return False
    snapshot = context_snapshot or {}
    context_plan = snapshot.get("context_plan")
    request_analysis = snapshot.get("request_analysis")
    required_domains = set()
    if isinstance(context_plan, dict):
        required_domains.update(
            str(domain).strip().lower()
            for domain in (context_plan.get("required_domains") or [])
            if str(domain).strip()
        )
    if isinstance(request_analysis, dict):
        required_domains.update(
            str(domain).strip().lower()
            for domain in (request_analysis.get("required_domains") or [])
            if str(domain).strip()
        )
    if not required_domains:
        return False
    return any(tool_name in SUMMARY_DOMAIN_FALLBACK_TOOLS.get(domain, set()) for domain in required_domains)


__all__ = [
    "clarification_gate_guard_result",
    "coding_intelligence_guard_result",
    "is_required_summary_domain_tool",
    "sanitize_tool_name",
]
