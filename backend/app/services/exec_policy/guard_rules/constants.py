"""Guard rule constants: rule keys, allowed actions and severities, and the custom-guard limits."""

from __future__ import annotations

AGENT_GUARD_RULES_KEY = "agent_guard_rules"
CUSTOM_TOOL_GUARD_RULES_KEY = "custom_tool_guard_rules"

AGENT_GUARD_ACTIONS = {"block", "review"}
CUSTOM_TOOL_GUARD_ACTIONS = {"audit", "block", "review"}
GUARD_ACTIONS = CUSTOM_TOOL_GUARD_ACTIONS
BLOCKING_GUARD_ACTIONS = {"block", "review"}
GUARD_SEVERITIES = {"info", "low", "medium", "high", "critical"}
MAX_CUSTOM_TOOL_GUARD_RULES = 100
MAX_CUSTOM_GUARD_LIST_ITEMS = 30
MAX_CUSTOM_GUARD_TEXT_LENGTH = 500
MAX_CUSTOM_GUARD_ARGUMENT_TEXT_LENGTH = 20_000
MAX_CUSTOM_GUARD_CONDITIONS = 40
MAX_CUSTOM_GUARD_CONDITION_DEPTH = 4
MAX_CUSTOM_GUARD_FIELD_LENGTH = 160

CUSTOM_GUARD_CONDITION_OPERATORS = {
    "equals",
    "not_equals",
    "contains",
    "not_contains",
    "starts_with",
    "ends_with",
    "in",
    "not_in",
    "any_in",
    "all_in",
    "any_not_in",
    "all_not_in",
    "exists",
    "not_exists",
    "greater_than",
    "greater_than_or_equals",
    "less_than",
    "less_than_or_equals",
    "matches_pattern",
}
