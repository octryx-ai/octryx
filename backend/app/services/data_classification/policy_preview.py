"""What a classification policy version changes, in words and in generated policies.

- :func:`change_lines` — every rule and the default level that differ between two contents, one line each;
- :func:`generated_policies` — the ``classification:<level>:…`` Cedar policies a content generates
  (``policy_engine.translator.matrix_policies``), for "View policy" and the diff of a draft;
- :func:`affected_workspaces` — how many active Workspaces sit at a level a change touches.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import Project
from ..model_gateway.data_policy.classification import (
    DATA_CLASSIFICATION_ORDER,
    DATA_POLICY_CONFIG_KEY,
    declared_classification,
)
from .effect_rules import (
    ALL_SERVERS,
    EFFECT_CATALOG,
    EFFECT_KNOWLEDGE_SHARING,
    EFFECT_MCP_SERVER,
    EFFECT_WEB_SEARCH,
    rules_from_content,
)
from .level_catalog import content_registry
from .levels import candidate_registry
from .policy_rules import CONNECTOR_FAMILIES, RULE_KEYS
from .policy_version_content import content_policy

# Rules that are stored and shown but have no enforcement point yet (the matrix marks them "Not enforced yet").
NOT_ENFORCED_RULES: frozenset[str] = frozenset({"transcript_retention_days"})

RULE_LABELS: dict[str, str] = {
    "seat_allowed": "Claude Code seat",
    "requires_governed_routing": "Company gateway required",
    "allowed_model_aliases": "Models cleared",
    "reranker_allowed": "Reranker",
    "remote_embeddings_allowed": "Remote embeddings",
    "log_masking_required": "Log tools",
    "device_runs_allowed": "Device runs",
    "transcript_retention_days": "Transcript retention",
    "connectors": "Connectors",
}
_BOOL_TEXT: dict[str, tuple[str, str]] = {
    "seat_allowed": ("allowed", "off"),
    "requires_governed_routing": ("required", "not required"),
    "reranker_allowed": ("allowed", "off"),
    "remote_embeddings_allowed": ("allowed", "off"),
    "log_masking_required": ("blocked until masking exists", "allowed"),
    "device_runs_allowed": ("allowed", "off"),
}
_ACCESS_TEXT = {"none": "none", "read": "read only", "read_write": "read & write"}


def value_text(rule: str, value: Any) -> str:
    if rule in _BOOL_TEXT:
        yes, no = _BOOL_TEXT[rule]
        return yes if value is True else no
    if rule == "transcript_retention_days":
        return "unlimited" if value is None else f"{value} days"
    if rule == "allowed_model_aliases":
        return "every cleared model" if value is None else f"{len(value)} models"
    return _ACCESS_TEXT.get(str(value), str(value))


def catalog_lines(before: Mapping[str, Any], after: Mapping[str, Any]) -> list[dict[str, Any]]:
    old, new = content_registry(before), content_registry(after)
    lines: list[dict[str, Any]] = []
    for level in new.levels:
        was = old.get(level.key)
        if was is None:
            lines.append({"level": level.key, "rule": "level_added", "before": None, "after": level.to_dict(),
                          "text": f"Level “{level.label}” added (rank {level.rank})"})
        elif (was.label, was.color, was.description, was.models_allowed) != (
                level.label, level.color, level.description, level.models_allowed):
            lines.append({"level": level.key, "rule": "level_changed", "before": was.to_dict(),
                          "after": level.to_dict(),
                          "text": f"Level “{was.label}” changed: {_level_change(was, level)}"})
    for level in old.levels:
        if level.key not in new:
            lines.append({"level": level.key, "rule": "level_retired", "before": level.to_dict(), "after": None,
                          "text": f"Level “{level.label}” retired"})
    return lines


def _level_change(was: Any, now: Any) -> str:
    parts = []
    if was.label != now.label:
        parts.append(f"name “{now.label}”")
    if was.color != now.color:
        parts.append("colour")
    if was.description != now.description:
        parts.append("description")
    if was.models_allowed != now.models_allowed:
        parts.append("models " + ("allowed" if now.models_allowed else "not allowed"))
    return ", ".join(parts)


def effect_lines(before: Mapping[str, Any], after: Mapping[str, Any]) -> list[dict[str, Any]]:
    old = {rule.rule_id: rule for rule in rules_from_content(before)}
    new = {rule.rule_id: rule for rule in rules_from_content(after)}
    lines: list[dict[str, Any]] = []
    for rule_id, rule in new.items():
        if old.get(rule_id) != rule:
            lines.append({"level": rule.from_level, "rule": f"effect:{rule_id}", "before": None,
                          "after": rule.to_dict(),
                          "text": f"Rule added: {rule_sentence(rule, content_registry(after))}"})
    for rule_id, rule in old.items():
        if rule_id not in new:
            lines.append({"level": rule.from_level, "rule": f"effect:{rule_id}", "before": rule.to_dict(),
                          "after": None, "text": f"Rule removed: {rule_sentence(rule, content_registry(before))}"})
    return lines


def rule_sentence(rule: Any, registry: Any) -> str:
    label = next((item["label"] for item in EFFECT_CATALOG if item["key"] == rule.effect), rule.effect)
    target = ""
    if rule.effect == EFFECT_MCP_SERVER:
        target = " every server" if rule.param == ALL_SERVERS else f" {rule.param}"
    level = registry.get(rule.from_level)
    return f"{label}{target} off at {level.label if level else rule.from_level} and above"


def effect_policies(content: Mapping[str, Any]) -> list[dict[str, str]]:
    """The Cedar text of the added rules, for review. The platform check named in the catalog enforces them."""
    registry = content_registry(content)
    policies = []
    for rule in rules_from_content(content):
        when = ("context.workspace has classification_rank && "
                f"context.workspace.classification_rank >= {registry.rank(rule.from_level)}")
        resource = {EFFECT_WEB_SEARCH: 'resource == Tool::"web_search"'}.get(rule.effect, "resource")
        action = "read_connector" if rule.effect == EFFECT_KNOWLEDGE_SHARING else "call_tool"
        policy_id = f"classification:{rule.from_level}+:{rule.rule_id.replace(':', '-')}"
        lines = [f"// {rule_sentence(rule, registry)}", f'@id("{policy_id}")',
                 f'forbid (principal, action == Action::"{action}", {resource})', f"  when {{ {when} }};"]
        policies.append({"id": policy_id, "text": "\n".join(lines)})
    return policies


def change_lines(before: Mapping[str, Any], after: Mapping[str, Any]) -> list[dict[str, Any]]:
    lines = catalog_lines(before, after) + effect_lines(before, after)
    known = content_registry(before)
    with candidate_registry(content_registry(after)):
        lines += _rule_lines(before, after, known)
    return lines


def _rule_lines(before: Mapping[str, Any], after: Mapping[str, Any], known: Any) -> list[dict[str, Any]]:
    old, new = content_policy(before), content_policy(after)
    lines: list[dict[str, Any]] = []
    if before.get("default_level") != after.get("default_level"):
        lines.append({"level": None, "rule": "default_level", "before": before.get("default_level"),
                      "after": after.get("default_level"),
                      "text": f"Level for new Workspaces: {before.get('default_level') or 'none'} → "
                              f"{after.get('default_level') or 'none'}"})
    for level in DATA_CLASSIFICATION_ORDER:
        if level not in known:
            continue  # an added level is one line ("Level … added"), its copied rules are not changes
        was, now = old.rules_for(level).to_dict(), new.rules_for(level).to_dict()
        for rule in RULE_KEYS:
            if rule == "connectors":
                for family in CONNECTOR_FAMILIES:
                    if was[rule][family] != now[rule][family]:
                        lines.append({"level": level, "rule": f"connectors.{family}", "before": was[rule][family],
                                      "after": now[rule][family],
                                      "text": f"{level} · {family}: {value_text(rule, was[rule][family])} → "
                                              f"{value_text(rule, now[rule][family])}"})
            elif was[rule] != now[rule]:
                lines.append({"level": level, "rule": rule, "before": was[rule], "after": now[rule],
                              "text": f"{level} · {RULE_LABELS[rule]}: {value_text(rule, was[rule])} → "
                                      f"{value_text(rule, now[rule])}"})
    return lines


def generated_policies(content: Mapping[str, Any]) -> list[dict[str, str]]:
    from ..policy_engine.translator import matrix_policies

    with candidate_registry(content_registry(content)):
        generated = [{"id": item.policy_id, "text": item.text} for item in matrix_policies(content_policy(content))]
    return generated + effect_policies(content)


def policy_diff(before: Mapping[str, Any], after: Mapping[str, Any]) -> dict[str, list[str]]:
    old = {item["id"]: item["text"] for item in generated_policies(before)}
    new = {item["id"]: item["text"] for item in generated_policies(after)}
    return {
        "added": sorted(set(new) - set(old)),
        "removed": sorted(set(old) - set(new)),
        "changed": sorted(key for key in set(old) & set(new) if old[key] != new[key]),
    }


async def workspace_levels(db: AsyncSession) -> list[tuple[str, str, str | None]]:
    """``(id, name, declared level)`` of every active Workspace, by name."""
    rows = (await db.execute(select(Project.id, Project.name, Project.config).where(Project.is_active.is_(True))
                             .order_by(Project.name))).all()
    return [(str(project_id), str(name), declared_classification(config.get(DATA_POLICY_CONFIG_KEY)
                                                                 if isinstance(config, dict) else None) or None)
            for project_id, name, config in rows]


async def affected_workspaces(db: AsyncSession, lines: list[dict[str, Any]]) -> int:
    levels = {line["level"] for line in lines if line["level"]}
    if not levels:
        return 0
    return sum(1 for _id, _name, level in await workspace_levels(db) if level in levels)


__all__ = [
    "NOT_ENFORCED_RULES",
    "RULE_LABELS",
    "affected_workspaces",
    "change_lines",
    "generated_policies",
    "policy_diff",
    "value_text",
    "workspace_levels",
]
