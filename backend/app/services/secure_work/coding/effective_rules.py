"""Coding → Effective rules: everything that limits the coding agent in
one Workspace, read only, each entry naming the one place it is edited.

- **Denied actions** — the published Cedar policies (Settings → Governance → Policies) that forbid ``write_path``,
  ``read_path`` or ``run_command`` and apply to the Workspace (scoped to it, or to every Workspace); the Workspace's
  generated tool rules (the baseline row);
- **Needs approval** — the Workspace's tool approval policy (Settings → Security → Tool & approval policies);
- **Who approves** — the platform approval rule (Settings → Governance → Approval rule);
- **Checks on every change** — the Delivery pipeline's checks.

Each tool rule also carries its parts (``kind``, ``command``, ``argument``, ``glob``, ``tools``) and its ``origin``
(``baseline``: one of the code-defined rules, also when a stored Workspace policy keeps a copy of it; ``workspace``:
added in the Workspace's settings), so the page can say it in words and where it comes from.
One rule is listed once: identical tool rules collapse into one entry (``ids`` names them all), and
the published Cedar policy generated from a listed tool rule (``workspace:<id>:tool-rule:<rule id>``) is not a second
entry: the tool rule names it in ``published_version``.
"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.agent_gateway.policy_keys import BASELINE_POLICY, POLICY_SOURCE_BASELINE

from ....models import Project
from ...agent_gateway.policy import build_policy, load_workspace_policy
from ...governance.approval_rule import load_approval_rule
from ...policy_engine.engine import cedar_module
from ...policy_engine.schema import ACTION_READ_PATH, ACTION_RUN_COMMAND, ACTION_WRITE_PATH
from ...policy_engine.store import published
from .pipeline_checks import checks_of, workspace_pipelines

CODING_ACTIONS = (ACTION_WRITE_PATH, ACTION_READ_PATH, ACTION_RUN_COMMAND)
EDIT_POLICIES = "policies"
EDIT_TOOL_POLICIES = "tool_policies"
EDIT_APPROVAL_RULE = "approval_rule"
EDIT_PIPELINE = "delivery_pipeline"


def _actions(body: dict[str, Any]) -> list[str]:
    constraint = body.get("action") or {}
    entities = constraint.get("entities") or ([constraint["entity"]] if constraint.get("entity") else [])
    return [str(entity.get("id")) for entity in entities if isinstance(entity, dict)]


def _tool_rule_entry(rule: Any, origin: str) -> dict[str, Any]:
    command = " ".join(rule.tokens)
    target = rule.glob or " ".join(part for part in (command, rule.argument) if part)
    return {
        "source": "tool_rule",
        "id": rule.id,
        "ids": [rule.id],
        "title": f"{rule.kind.replace('_', ' ')}: {target}",
        "actions": [ACTION_RUN_COMMAND if rule.kind.startswith("command") else ACTION_WRITE_PATH],
        "detail": "Workspace tool rule",
        "edit": EDIT_POLICIES,
        "kind": rule.kind,
        "command": command,
        "argument": rule.argument,
        "glob": rule.glob,
        "tools": sorted(rule.tools),
        "origin": origin,
        "published_version": None,
    }


def _same_rule_key(entry: dict[str, Any]) -> tuple[Any, ...]:
    return (entry["kind"], entry["command"], entry["argument"], entry["glob"], tuple(entry["tools"]))


def _baseline_keys() -> set[tuple[Any, ...]]:
    rules = build_policy(BASELINE_POLICY, source=POLICY_SOURCE_BASELINE).tool_rules
    return {_same_rule_key(_tool_rule_entry(rule, POLICY_SOURCE_BASELINE)) for rule in rules}


def _tool_rule_entries(rules: Any, source: str) -> list[dict[str, Any]]:
    baseline = _baseline_keys()
    entries: dict[tuple[Any, ...], dict[str, Any]] = {}
    for rule in rules:
        entry = _tool_rule_entry(rule, source)
        if source == POLICY_SOURCE_BASELINE or _same_rule_key(entry) in baseline:
            entry["origin"] = POLICY_SOURCE_BASELINE
        same = entries.get(_same_rule_key(entry))
        if same is None:
            entries[_same_rule_key(entry)] = entry
        else:
            same["ids"].append(rule.id)
    return list(entries.values())


def _merge_generated(
    denied: list[dict[str, Any]], tool_rules: list[dict[str, Any]], project_id: str
) -> list[dict[str, Any]]:
    """The published policies without those generated from a listed tool rule; that tool rule names the version."""
    by_id = {rule_id: entry for entry in tool_rules for rule_id in entry["ids"]}
    prefix = f"workspace:{project_id}:tool-rule:"
    kept = []
    for entry in denied:
        policy_id = str(entry.get("id") or "")
        generated = by_id.get(policy_id.removeprefix(prefix)) if policy_id.startswith(prefix) else None
        if generated is None:
            kept.append(entry)
        else:
            generated["published_version"] = entry.get("version")
    return kept


def _published_denials(text: str, project_id: str, version: int | None) -> list[dict[str, Any]]:
    if not text.strip():
        return []
    try:
        est = json.loads(cedar_module().policies_to_json_str(text))
    except Exception:  # noqa: BLE001 - an unparseable published set is alerted by the runtime; nothing to list
        return []
    rules = []
    for body in (est.get("staticPolicies") or {}).values():
        actions = [name for name in _actions(body) if name in CODING_ACTIONS]
        unconstrained = (body.get("action") or {}).get("op") == "All"
        if body.get("effect") != "forbid" or not (actions or unconstrained):
            continue
        conditions = json.dumps(body.get("conditions") or [])
        if '"Workspace"' in conditions and project_id not in conditions:
            continue  # scoped to other Workspaces
        annotations = body.get("annotations") or {}
        rules.append(
            {
                "source": "policy",
                "id": annotations.get("id"),
                "title": annotations.get("name") or annotations.get("id"),
                "actions": actions or list(CODING_ACTIONS),
                "detail": f"Published policy set v{version}",
                "edit": EDIT_POLICIES,
                "version": version,
            }
        )
    return rules


async def effective_rules(db: AsyncSession, project_id: str) -> dict[str, Any]:
    current = await published(db)
    denied = _published_denials(
        current.policies_text if current else "", project_id, current.version if current else None
    )
    loaded = await load_workspace_policy(db, project_id)
    tool_rules = _tool_rule_entries(loaded.policy.tool_rules if loaded.policy is not None else (), loaded.source)
    denied = _merge_generated(denied, tool_rules, project_id) + tool_rules
    project = await db.get(Project, project_id)
    approval = dict((project.config or {}).get("approval_policy") or {}) if project is not None else {}
    needs_approval = [{"kind": "risk", "value": str(value)} for value in approval.get("require_for_risks") or []]
    needs_approval += [{"kind": "tool", "value": str(value)} for value in approval.get("require_for_tools") or []]
    checks = [
        {"pipeline": config.name, **check}
        for config in await workspace_pipelines(db, project_id)
        for check in checks_of(config)
    ]
    return {
        "project_id": project_id,
        "denied": denied,
        "needs_approval": {
            "items": needs_approval,
            "exempt_tools": list(approval.get("exempt_tools") or []),
            "edit": EDIT_TOOL_POLICIES,
        },
        "who_approves": {"rule": await load_approval_rule(db), "edit": EDIT_APPROVAL_RULE},
        "checks": {"items": checks, "edit": EDIT_PIPELINE},
    }


__all__ = ["effective_rules"]
