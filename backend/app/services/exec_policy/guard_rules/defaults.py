"""Built-in agent guard rules and their normalization against stored overrides."""

from __future__ import annotations

import copy
from typing import Any

from .constants import AGENT_GUARD_ACTIONS, AGENT_GUARD_RULES_KEY, GUARD_SEVERITIES

DEFAULT_AGENT_GUARD_RULES: list[dict[str, Any]] = [
    {
        "id": "coding_prewrite_intelligence_required",
        "label": "Require repository intelligence before code writes",
        "description": "Blocks source-code writes until the agent has inspected the repository or relevant symbols.",
        "phase": "pre_tool_call",
        "category": "coding",
        "action": "block",
        "severity": "high",
        "enabled": True,
        "locked": False,
    },
    {
        # Persisted exec-policy overrides name this id; the envelope is the
        # coding-run work item.
        "id": "work_package_clarification_required",
        "label": "Require resolved coding-run clarification",
        "description": "Blocks source-code writes while clarification questions are still unresolved.",
        "phase": "pre_tool_call",
        "category": "coding",
        "action": "block",
        "severity": "high",
        "enabled": True,
        "locked": False,
    },
    {
        "id": "technical_source_credibility_required",
        "label": "Require credible technical sources",
        "description": "Blocks weak sources for technical research when official evidence is expected.",
        "phase": "pre_tool_call",
        "category": "research",
        "action": "block",
        "severity": "medium",
        "enabled": True,
        "locked": False,
    },
    {
        "id": "code_structure_diagram_evidence_required",
        "label": "Require code-structure snapshot evidence before code diagrams",
        "description": (
            "Blocks drawing a diagram in code-structure diagram workflows until the code structure (with its "
            "classes) was read in the same turn."
        ),
        "phase": "pre_tool_call",
        "category": "diagram",
        "action": "block",
        "severity": "medium",
        "enabled": True,
        "locked": False,
    },
    {
        "id": "aws_topology_snapshot_already_collected",
        "label": "Avoid duplicate AWS topology snapshots",
        "description": "Stops topology snapshot calls when the requested services were already collected.",
        "phase": "pre_tool_call",
        "category": "aws",
        "action": "block",
        "severity": "low",
        "enabled": True,
        "locked": False,
    },
]

_DEFAULT_BY_ID = {str(rule["id"]): rule for rule in DEFAULT_AGENT_GUARD_RULES}


def default_agent_guard_rules() -> list[dict[str, Any]]:
    return copy.deepcopy(DEFAULT_AGENT_GUARD_RULES)


def normalize_agent_guard_rules(raw_rules: Any) -> list[dict[str, Any]]:
    raw_items = raw_rules if isinstance(raw_rules, list) else []
    configured = {
        str(item.get("id") or "").strip(): item
        for item in raw_items
        if isinstance(item, dict) and str(item.get("id") or "").strip()
    }
    normalized: list[dict[str, Any]] = []
    for guard_id, default_rule in _DEFAULT_BY_ID.items():
        incoming = configured.get(guard_id, {})
        action = str(incoming.get("action") or default_rule["action"]).strip().lower()
        severity = str(incoming.get("severity") or default_rule["severity"]).strip().lower()
        locked = bool(default_rule.get("locked"))
        enabled = bool(incoming.get("enabled", default_rule["enabled"]))
        if locked:
            enabled = True
        normalized.append(
            {
                **copy.deepcopy(default_rule),
                "enabled": enabled,
                "action": action if action in AGENT_GUARD_ACTIONS else default_rule["action"],
                "severity": severity if severity in GUARD_SEVERITIES else default_rule["severity"],
                "locked": locked,
            }
        )
    return normalized


def agent_guard_rule(config: dict[str, Any] | None, guard_id: str) -> dict[str, Any]:
    rules = normalize_agent_guard_rules((config or {}).get(AGENT_GUARD_RULES_KEY))
    for rule in rules:
        if str(rule.get("id") or "") == guard_id:
            return rule
    default = _DEFAULT_BY_ID.get(guard_id)
    return copy.deepcopy(default) if default else {}


def agent_guard_enabled(config: dict[str, Any] | None, guard_id: str) -> bool:
    rule = agent_guard_rule(config, guard_id)
    return bool(rule.get("enabled"))

