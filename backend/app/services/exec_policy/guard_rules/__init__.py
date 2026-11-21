"""Exec Policy guard rules: built-in agent guards and admin-defined custom tool guards.

Callers import from ``exec_policy.guard_rules``.
"""

from __future__ import annotations

from .constants import AGENT_GUARD_RULES_KEY, CUSTOM_TOOL_GUARD_RULES_KEY
from .custom import apply_agent_guard_metadata, custom_tool_guard_decisions, custom_tool_guard_result
from .defaults import (
    DEFAULT_AGENT_GUARD_RULES,
    agent_guard_enabled,
    agent_guard_rule,
    default_agent_guard_rules,
    normalize_agent_guard_rules,
)
from .normalize import normalize_custom_tool_guard_rules

__all__ = [
    "AGENT_GUARD_RULES_KEY",
    "CUSTOM_TOOL_GUARD_RULES_KEY",
    "DEFAULT_AGENT_GUARD_RULES",
    "agent_guard_enabled",
    "agent_guard_rule",
    "apply_agent_guard_metadata",
    "custom_tool_guard_decisions",
    "custom_tool_guard_result",
    "default_agent_guard_rules",
    "normalize_agent_guard_rules",
    "normalize_custom_tool_guard_rules",
]
