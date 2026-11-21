"""Denials of the run-bound PreToolUse decision (``tool_policy``): reasons, the phase's write and test tools."""

from __future__ import annotations

from typing import Any

from ...agent_gateway.tool_check import DECISION_ALLOW, DECISION_DENY, ToolDecision, setting_remedy

REASON_RUN_PAUSED = "run_paused"
REASON_RUN_WAITING = "run_waiting"
REASON_OUTSIDE_PHASE_TOOLS = "outside_phase_tools"
REASON_PHASE_PATH = "phase_path_rule"
REASON_CONFIRMED_TEST = "confirmed_test_protected"
REASON_PROTECTED_PATH = "protected_path"
REASON_SCM_CLIENT = "platform_action_required"
REASON_PUSH_BY_PLATFORM = "push_by_platform"
REASON_AGENT_TOOLS_DENY = "agent_tools_deny"
REASON_HARD_DENY = "run_hard_deny"
REASON_ROLE_COMMAND = "work_role_command_rule"

PLATFORM_WRITE_TOOLS = frozenset({"write_workspace_file", "edit_workspace_file", "multi_edit_workspace_file",
                                  "apply_patch_workspace"})
TEST_TOOLS = frozenset({"run_test_suite"})


def _deny(reason: str, message: str) -> ToolDecision:
    return ToolDecision(DECISION_DENY, "denied", reason, reason.replace("_", "-"), message)


def _with_remedy(decision: ToolDecision, setting: str, value: Any, defaults: dict[str, Any] | None) -> ToolDecision:
    """``decision`` with the admin's one-click fix, when the Workspace's ``tool_defaults`` decided it."""
    if defaults is None:
        return decision
    return ToolDecision(decision.decision, decision.state, decision.reason, decision.rule_id,
                        decision.message + " A Workspace admin can allow it (Workspace settings › Coding tools & "
                        "devices › Tool defaults).",
                        remedy=setting_remedy(setting, value))


def _allows(decision: ToolDecision | None) -> bool:
    return decision is not None and decision.decision == DECISION_ALLOW
