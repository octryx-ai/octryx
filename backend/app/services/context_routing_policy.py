"""Explicit, config-overridable context tier routing policy.

Owns the DECISION TABLE that selects a turn's context tier and route reason.
Every rule matches only explicit inputs of the turn: the agent mode's
capability, an agent blueprint, the session's task/parent context, the
Workspace, and the conversation's size (history count, persisted summary).
The prompt text is never an input: no rule guesses a knowledge lookup, a
presentation, a summary digest, a shell command, an admin request, a
continuation or a greeting from the wording.

Rules are evaluated top to bottom; the first enabled matching rule wins.
``default_standard`` is the terminal fallback and always applies.

Project override contract (additive, default empty)::

    project_config["context_routing_policy"] = {
        "tier_overrides": {"<rule_id>": "<tier>"},   # re-tier a matched rule
        "disabled_rules": ["<rule_id>", ...],        # fall through to next rule
    }

Unknown rule ids and an ``enabled_rules`` key are ignored. Every decision is audited:
:class:`ContextRoutingDecision` carries rule id, tier, route reason, and source;
the planner copies rule id and source onto ``ContextPlan.routing_rule_id`` /
``routing_rule_source``.

The tool surface is not decided here: ``agent/core/context/turn_tool_surface.py``
resolves it from explicit sources only.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

VALID_CONTEXT_TIERS = frozenset({"minimal", "standard", "full", "admin"})
ROUTING_SOURCE_DEFAULT_POLICY = "default_policy"
ROUTING_SOURCE_PROJECT_OVERRIDE = "project_override"
FALLBACK_RULE_ID = "default_standard"
PROJECT_CONFIG_ROUTING_POLICY_KEY = "context_routing_policy"


@dataclass(frozen=True, slots=True)
class ContextRoutingSignals:
    """Explicit boolean/count inputs the decision table matches against (never prompt-derived)."""

    is_admin_agent: bool = False
    is_change_agent: bool = False
    has_task_context: bool = False
    has_parent_context: bool = False
    has_project: bool = False
    history_count: int = 0
    has_summary: bool = False


@dataclass(frozen=True, slots=True)
class ContextRoutingRule:
    rule_id: str
    tier: str
    route_reason: str
    description: str
    matches: Callable[[ContextRoutingSignals], bool]


@dataclass(frozen=True, slots=True)
class ContextRoutingDecision:
    rule_id: str
    tier: str
    route_reason: str
    source: str  # ROUTING_SOURCE_DEFAULT_POLICY | ROUTING_SOURCE_PROJECT_OVERRIDE


DEFAULT_CONTEXT_ROUTING_RULES: tuple[ContextRoutingRule, ...] = (
    ContextRoutingRule(
        "admin_capability", "full", "admin_capability",
        "The agent mode has the admin capability: full context, admin prompt variant.",
        lambda s: s.is_admin_agent,
    ),
    ContextRoutingRule(
        # Stored scenario/budget/context-prompt configurations name this id; the rule reads no
        # continuation wording.
        "change_or_continuation", "full", "change_or_continuation",
        "Change capability, an agent blueprint, or task/parent-session context: full working context.",
        lambda s: s.is_change_agent or s.has_task_context or s.has_parent_context,
    ),
    ContextRoutingRule(
        "contextual_request", "standard", "contextual_request",
        "A Workspace, conversation history or a persisted summary exists: standard tier with history.",
        lambda s: s.has_project or s.history_count > 0 or s.has_summary,
    ),
    ContextRoutingRule(
        FALLBACK_RULE_ID, "standard", "default_standard",
        "Terminal fallback: a fresh conversation outside a Workspace, standard tier.",
        lambda s: True,
    ),
)


def resolve_context_routing_overrides(
    project_config: dict[str, Any] | None,
) -> tuple[dict[str, str], frozenset[str]]:
    """Parse and sanitize the project override contract (invalid entries are ignored)."""
    policy = (project_config or {}).get(PROJECT_CONFIG_ROUTING_POLICY_KEY)
    if not isinstance(policy, dict):
        return {}, frozenset()
    known_rule_ids = {rule.rule_id for rule in DEFAULT_CONTEXT_ROUTING_RULES}
    raw_tiers = policy.get("tier_overrides")
    tier_overrides = {
        str(rule_id): str(tier)
        for rule_id, tier in (raw_tiers.items() if isinstance(raw_tiers, dict) else ())
        if str(rule_id) in known_rule_ids and str(tier) in VALID_CONTEXT_TIERS
    }
    raw_disabled = policy.get("disabled_rules")
    disabled_rules = frozenset(
        str(rule_id)
        for rule_id in (raw_disabled if isinstance(raw_disabled, (list, tuple, set)) else ())
        if str(rule_id) in known_rule_ids
    )
    return tier_overrides, disabled_rules


def evaluate_context_routing(
    signals: ContextRoutingSignals,
    project_config: dict[str, Any] | None = None,
) -> ContextRoutingDecision:
    """Evaluate the decision table top to bottom and return the audited routing decision."""
    tier_overrides, disabled_rules = resolve_context_routing_overrides(project_config)
    for rule in DEFAULT_CONTEXT_ROUTING_RULES:
        if rule.rule_id in disabled_rules and rule.rule_id != FALLBACK_RULE_ID:
            continue
        if not rule.matches(signals):
            continue
        tier, source = rule.tier, ROUTING_SOURCE_DEFAULT_POLICY
        override_tier = tier_overrides.get(rule.rule_id)
        if override_tier is not None and override_tier != rule.tier:
            tier, source = override_tier, ROUTING_SOURCE_PROJECT_OVERRIDE
        return ContextRoutingDecision(rule.rule_id, tier, rule.route_reason, source)
    fallback = DEFAULT_CONTEXT_ROUTING_RULES[-1]
    return ContextRoutingDecision(fallback.rule_id, fallback.tier, fallback.route_reason, ROUTING_SOURCE_DEFAULT_POLICY)
