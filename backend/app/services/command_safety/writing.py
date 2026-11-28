"""Command safety writes: validate and store the platform gate or a Workspace override."""

from __future__ import annotations

import json
import uuid
from collections.abc import Mapping
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.exec_policy.policy_config import with_removed_defaults

from ...models import AuditLog, ExecPolicyConfig, Project
from ..exec_policy.guard_rules import AGENT_GUARD_RULES_KEY, CUSTOM_TOOL_GUARD_RULES_KEY
from ..exec_policy.service import get_effective_exec_policy_config, upsert_global_exec_policy_config
from ..system_config.constants import (
    AGENT_LLM_SECURITY_ANALYZER_DENY_THRESHOLD_KEY,
    AGENT_LLM_SECURITY_ANALYZER_REVIEW_THRESHOLD_KEY,
    AGENT_LLM_SECURITY_ANALYZER_TIMEOUT_SECONDS_KEY,
    AGENT_SECURITY_ANALYZER_CHAIN_KEY,
)
from ..system_config.values import set_system_config_value
from .contract import (
    AUDIT_ACTION,
    AUDIT_WORKSPACE_ACTION,
    CHECK_KEYS,
    ERROR_INVALID,
    ERROR_NO_CHECK,
    ERROR_THRESHOLDS,
    LIST_FIELDS,
    LLM_BOUNDS,
    LLM_KEYS,
    MAX_ITEM_CHARS,
    MAX_ITEMS,
    OVERRIDE_ROW_NAME,
    CommandSafetyError,
)
from .reading import _bundle, _override_row, differences, platform_settings, workspace_settings


def _checked_list(value: Any, path: str) -> list[str]:
    if not isinstance(value, list) or len(value) > MAX_ITEMS:
        raise CommandSafetyError(ERROR_INVALID, path)
    items = [str(item).strip() for item in value if str(item).strip()]
    if any(len(item) > MAX_ITEM_CHARS for item in items):
        raise CommandSafetyError(ERROR_INVALID, path)
    return list(dict.fromkeys(items))


def _checked_core(body: Mapping[str, Any]) -> tuple[list[str], dict[str, int], dict[str, list[str]]]:
    checks = body.get("checks")
    if not isinstance(checks, Mapping) or any(key not in CHECK_KEYS or type(value) is not bool
                                              for key, value in checks.items()):
        raise CommandSafetyError(ERROR_INVALID, "checks")
    chain = [key for key in CHECK_KEYS if checks.get(key) is True]
    if not chain:
        raise CommandSafetyError(ERROR_NO_CHECK, "checks")
    llm_raw = body.get("llm_risk")
    if not isinstance(llm_raw, Mapping):
        raise CommandSafetyError(ERROR_INVALID, "llm_risk")
    llm: dict[str, int] = {}
    for field, (low, high) in LLM_BOUNDS.items():
        value = llm_raw.get(field)
        if type(value) is not int or not low <= value <= high:
            raise CommandSafetyError(ERROR_INVALID, f"llm_risk.{field}")
        llm[field] = value
    if llm["deny_threshold"] < llm["review_threshold"]:
        raise CommandSafetyError(ERROR_THRESHOLDS, "llm_risk.deny_threshold")
    raw_lists = body.get("lists")
    if not isinstance(raw_lists, Mapping):
        raise CommandSafetyError(ERROR_INVALID, "lists")
    lists = {LIST_FIELDS[field]: _checked_list(raw_lists.get(field, []), f"lists.{field}") for field in LIST_FIELDS}
    return chain, llm, lists


def _rules_with_switches(rules: list[Any], switches: Any, path: str) -> list[Any]:
    if switches is None:
        return rules
    if not isinstance(switches, Mapping) or any(type(value) is not bool for value in switches.values()):
        raise CommandSafetyError(ERROR_INVALID, path)
    return [{**rule, "enabled": switches.get(rule.get("id"), rule.get("enabled", True))}
            if isinstance(rule, Mapping) and not rule.get("locked") else rule for rule in rules]


async def save_platform_settings(db: AsyncSession, body: Mapping[str, Any], *, actor_id: str) -> dict[str, Any]:
    chain, llm, lists = _checked_core(body)
    before = await platform_settings(db)
    exec_config = await get_effective_exec_policy_config(db)
    guard_rules = _rules_with_switches(list(exec_config.get(AGENT_GUARD_RULES_KEY) or []), body.get("guard_rules"),
                                       "guard_rules")
    custom_rules = _rules_with_switches(list(exec_config.get(CUSTOM_TOOL_GUARD_RULES_KEY) or []),
                                        body.get("custom_guard_rules"), "custom_guard_rules")
    writes = {AGENT_SECURITY_ANALYZER_CHAIN_KEY: json.dumps(chain),
              AGENT_LLM_SECURITY_ANALYZER_TIMEOUT_SECONDS_KEY: str(llm["timeout_seconds"]),
              AGENT_LLM_SECURITY_ANALYZER_REVIEW_THRESHOLD_KEY: str(llm["review_threshold"]),
              AGENT_LLM_SECURITY_ANALYZER_DENY_THRESHOLD_KEY: str(llm["deny_threshold"])}
    for key, value in writes.items():
        await set_system_config_value(db, key=key, value=value,
                                      description="Command safety (Settings → Security)")
    await upsert_global_exec_policy_config(db, {**lists, AGENT_GUARD_RULES_KEY: guard_rules,
                                                CUSTOM_TOOL_GUARD_RULES_KEY: custom_rules})
    after = await platform_settings(db)
    db.add(AuditLog(user_id=actor_id, action=AUDIT_ACTION, resource_type="command_safety", resource_id="platform",
                    details={"changes": differences(before, after)}))
    await db.flush()
    return after


async def save_workspace_settings(db: AsyncSession, project: Project, body: Mapping[str, Any], *,
                                  actor_id: str) -> dict[str, Any]:
    from ..admin.project.admin_project_config_service import apply_project_config_patch

    mode = body.get("mode")
    if mode not in {"inherit", "override"}:
        raise CommandSafetyError(ERROR_INVALID, "mode")
    platform = await platform_settings(db)
    config = dict(project.config or {}) if isinstance(project.config, Mapping) else {}
    stored_policy = config.get("runtime_policy")
    runtime_policy = dict(stored_policy) if isinstance(stored_policy, Mapping) else {}
    bundle = {key: value for key, value in _bundle(config).items()
              if key not in {"security_analyzer_chain", *LLM_KEYS.values()}}
    row = await _override_row(db, project.id)
    project_lists: dict[str, list[str]] = {}
    if mode == "override":
        settings = body.get("settings")
        if not isinstance(settings, Mapping):
            raise CommandSafetyError(ERROR_INVALID, "settings")
        chain, llm, lists = _checked_core(settings)
        if chain != [item["key"] for item in platform["checks"] if item["enabled"]]:
            bundle["security_analyzer_chain"] = chain
        bundle.update({key: llm[field] for field, key in LLM_KEYS.items()
                       if llm[field] != platform["llm_risk"].get(field)})
        platform_lists = {LIST_FIELDS[field]: values for field, values in platform["lists"].items()}
        project_lists = {key: values for key, values in lists.items() if values != platform_lists.get(key)}
    runtime_policy["default_bundle"] = bundle
    await apply_project_config_patch(db, project=project, patch={"runtime_policy": runtime_policy},
                                     actor_user_id=actor_id)
    if project_lists:
        if row is None:
            row = ExecPolicyConfig(id=str(uuid.uuid4()), name=OVERRIDE_ROW_NAME, project_id=project.id, priority=100,
                                   is_active=True, config_json=with_removed_defaults(project_lists))
            db.add(row)
        else:
            row.config_json, row.is_active = with_removed_defaults(project_lists), True
    elif row is not None:
        await db.delete(row)
    await db.flush()
    after = await workspace_settings(db, project)
    db.add(AuditLog(user_id=actor_id, action=AUDIT_WORKSPACE_ACTION, resource_type="workspace", resource_id=project.id,
                    details={"mode": after["mode"], "differences": after["differences"]}))
    await db.flush()
    return after
