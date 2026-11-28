"""The ``device_runs`` section of ``agent_gateway_policy``: names, defaults and validation."""

from __future__ import annotations

import re
from typing import Any

DEVICE_RUNS_KEY = "device_runs"
PROFILES = ("governed", "seat")
DEFAULTS: dict[str, Any] = {
    "enabled": True,
    "allowed_profiles": list(PROFILES),
    "approval_timeout_s": 300,
    "max_job_minutes": 60,
    "allow_job_edit_scope": True,
    "chat_approvals_confirm_changes": True,
    "stale_turn_minutes": 10,
    "sensitive_content_requires_governed": False,
    "run_turns_ask_before_edits": False,
    # A local open model by default: no Anthropic API cost for the platform's own turns.
    "run_turn_models": {"read_only": "gemma-4-31b", "change": "gemma-4-31b", "deliver": "gemma-4-31b"},
    # The seat's model per model class (plan | implement | review | role) in this
    # Workspace, over the installation's (``workflow_runs/octryx/seat_models``); empty = the installation's.
    "seat_models": {},
    # What earlier runs of the app learned goes into the phase brief as
    # information (``workflow_runs/run_memory``); a Workspace switches it off with false.
    "run_memory": True,
    "browser_phases": [],
    "research_phases": [],
    "research_min_sources": 3,
    # How often a failed check sends a run's work back before it pauses as checks_failed (workflow_runs/check_attempts).
    "check_attempts": 3,
    # Path classes whose change needs an approved plan (workflow_runs/plan_scope); None = the platform's, {} = none.
    "expensive_paths": None,
    "tool_defaults": {},
}
# The first value of each choice is the default (allow by default, block as an admin option).
TOOL_DEFAULT_CHOICES: dict[str, tuple[str, ...]] = {
    "unknown_tools": ("allow", "deny"),
    "web_tools": ("all", "research_only", "off"),
    "shell": ("free", "strict"),
    "path_rules": ("log", "strict"),
    "device_models": ("nearest", "list_only"),
    "network": ("open", "allowlist"),
    "browser": ("read_external", "loopback"),
}
MAX_ALLOWED_TOOLS = 100
MAX_TOOL_NAME_CHARS = 200
MAX_BROWSER_PHASES = 20
MAX_BROWSER_PHASE_CHARS = 120
_BROWSER_PHASE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]*\.[A-Za-z0-9_][A-Za-z0-9_.:-]*")
CAPABILITY_CLASSES = ("read_only", "change", "deliver")
_FLAGS = ("enabled", "allow_job_edit_scope", "chat_approvals_confirm_changes", "sensitive_content_requires_governed",
          "run_turns_ask_before_edits", "run_memory")
_BOUNDS = {"approval_timeout_s": (30, 3600), "max_job_minutes": (1, 1440), "stale_turn_minutes": (1, 1440),
           "research_min_sources": (1, 20), "check_attempts": (1, 20)}


class DeviceRunsPolicyError(ValueError):
    def __init__(self, reason: str, path: str) -> None:
        super().__init__(f"{path}: {reason}")
        self.reason = reason
        self.path = path


def _seat_models(value: Any, path: str) -> dict[str, str]:
    from ..workflow_runs.octryx.seat_models import MAX_MODEL_CHARS, classes

    if not isinstance(value, dict) or set(value) - set(classes()) or any(
            not isinstance(item, str) or not item.strip() or len(item) > MAX_MODEL_CHARS for item in value.values()):
        raise DeviceRunsPolicyError("invalid_seat_models", path)
    return {key: item.strip() for key, item in value.items()}


def normalize_device_runs(value: Any, path: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) - set(DEFAULTS):
        raise DeviceRunsPolicyError("invalid_device_runs", path)
    normalized: dict[str, Any] = {}
    for key in _FLAGS:
        if key in value:
            if type(value[key]) is not bool:
                raise DeviceRunsPolicyError("invalid_flag", f"{path}.{key}")
            normalized[key] = value[key]
    if "allowed_profiles" in value:
        profiles = value["allowed_profiles"]
        if not isinstance(profiles, list) or not profiles or any(item not in PROFILES for item in profiles):
            raise DeviceRunsPolicyError("invalid_profiles", f"{path}.allowed_profiles")
        normalized["allowed_profiles"] = [profile for profile in PROFILES if profile in profiles]
    if "run_turn_models" in value:
        models = value["run_turn_models"]
        if not isinstance(models, dict) or set(models) - set(CAPABILITY_CLASSES) or any(
                not isinstance(item, str) or len(item) > 120 for item in models.values()):
            raise DeviceRunsPolicyError("invalid_run_turn_models", f"{path}.run_turn_models")
        normalized["run_turn_models"] = {key: item.strip() for key, item in models.items()}
    if "seat_models" in value:
        normalized["seat_models"] = _seat_models(value["seat_models"], f"{path}.seat_models")
    if "browser_phases" in value:
        normalized["browser_phases"] = _browser_phases(value["browser_phases"], f"{path}.browser_phases")
    if "research_phases" in value:
        normalized["research_phases"] = _browser_phases(value["research_phases"], f"{path}.research_phases",
                                                        reason="invalid_research_phases")
    if "tool_defaults" in value:
        normalized["tool_defaults"] = _tool_defaults(value["tool_defaults"], f"{path}.tool_defaults")
    if "expensive_paths" in value:  # None goes back to the platform's classes
        normalized["expensive_paths"] = (None if value["expensive_paths"] is None else
                                         _expensive_paths(value["expensive_paths"], f"{path}.expensive_paths"))
    for key, (low, high) in _BOUNDS.items():
        if key in value:
            if type(value[key]) is not int or not low <= value[key] <= high:
                raise DeviceRunsPolicyError("invalid_number", f"{path}.{key}")
            normalized[key] = value[key]
    return normalized


def _expensive_paths(value: Any, path: str) -> dict[str, list[str]]:
    if not isinstance(value, dict) or len(value) > 20 or any(
            not isinstance(key, str) or not re.fullmatch(r"[a-z][a-z0-9_]{0,39}", key) or not isinstance(globs, list)
            or len(globs) > 50 or any(not isinstance(glob, str) or not glob.strip() or len(glob) > 200
                                      for glob in globs) for key, globs in value.items()):
        raise DeviceRunsPolicyError("invalid_expensive_paths", path)
    return {key: [glob.strip() for glob in globs] for key, globs in value.items()}


def _browser_phases(value: Any, path: str, *, reason: str = "invalid_browser_phases") -> list[str]:
    if not isinstance(value, list) or len(value) > MAX_BROWSER_PHASES or any(
            not isinstance(item, str) or len(item.strip()) > MAX_BROWSER_PHASE_CHARS
            or not _BROWSER_PHASE.fullmatch(item.strip()) for item in value):
        raise DeviceRunsPolicyError(reason, path)
    return list(dict.fromkeys(item.strip() for item in value))


def _tool_defaults(value: Any, path: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) - {*TOOL_DEFAULT_CHOICES, "allowed_tools"}:
        raise DeviceRunsPolicyError("invalid_tool_defaults", path)
    normalized: dict[str, Any] = {}
    # A write merges key by key (parallel edits never overwrite each other); ``None`` resets
    # a key to its default (``merge_tool_defaults``).
    for key, choices in TOOL_DEFAULT_CHOICES.items():
        if key in value:
            if value[key] is not None and value[key] not in choices:
                raise DeviceRunsPolicyError("invalid_tool_default", f"{path}.{key}")
            normalized[key] = value[key]
    if value.get("allowed_tools", ...) is None:
        normalized["allowed_tools"] = None
    elif "allowed_tools" in value:
        tools = value["allowed_tools"]
        if not isinstance(tools, list) or len(tools) > MAX_ALLOWED_TOOLS or any(
                not isinstance(item, str) or not item.strip() or len(item) > MAX_TOOL_NAME_CHARS for item in tools):
            raise DeviceRunsPolicyError("invalid_allowed_tools", f"{path}.allowed_tools")
        normalized["allowed_tools"] = list(dict.fromkeys(item.strip() for item in tools))
    return normalized


def merge_tool_defaults(stored: Any, patch: dict[str, Any]) -> dict[str, Any]:
    merged = dict(stored) if isinstance(stored, dict) else {}
    for key, item in patch.items():
        default = TOOL_DEFAULT_CHOICES[key][0] if key in TOOL_DEFAULT_CHOICES else []
        if item is None or item == default:
            merged.pop(key, None)
        else:
            merged[key] = item
    return merged


def tool_defaults(device_runs: Any) -> dict[str, Any]:
    stored = dict(device_runs.get("tool_defaults") or {}) if isinstance(device_runs, dict) else {}
    effective: dict[str, Any] = {key: choices[0] for key, choices in TOOL_DEFAULT_CHOICES.items()}
    effective.update({key: stored[key] for key in TOOL_DEFAULT_CHOICES if stored.get(key) in
                      TOOL_DEFAULT_CHOICES[key]})
    tools = stored.get("allowed_tools")
    effective["allowed_tools"] = [str(item) for item in tools] if isinstance(tools, list) else []
    return effective


def browser_phase_key(workflow_key: str, node_id: str) -> str:
    return f"{workflow_key}.{node_id}"


def device_runs_section(raw_policy: Any) -> dict[str, Any]:
    stored = raw_policy.get(DEVICE_RUNS_KEY) if isinstance(raw_policy, dict) else None
    return {**DEFAULTS, **(stored if isinstance(stored, dict) else {})}


__all__ = ["DEFAULTS", "DEVICE_RUNS_KEY", "DeviceRunsPolicyError", "browser_phase_key",
           "merge_tool_defaults", "tool_defaults",
           "device_runs_section", "normalize_device_runs"]
