"""Command safety reads: the platform gate, a Workspace's effective gate and what differs."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.exec_policy.policy_config import DEFAULT_ALLOW_KEYS, DEFAULT_EXEC_POLICY_CONFIG, removed_key

from ...models import ExecPolicyConfig, Project
from ..exec_policy.guard_rules import AGENT_GUARD_RULES_KEY, CUSTOM_TOOL_GUARD_RULES_KEY
from ..exec_policy.service import get_effective_exec_policy_config
from ..system_config.runtime_settings import get_agent_runtime_settings
from .contract import CHECKS, LIST_FIELDS, LLM_KEYS, OVERRIDE_ROW_NAME


def _lists(config: Mapping[str, Any]) -> dict[str, list[str]]:
    return {field: [str(item) for item in config.get(key) or []] for field, key in LIST_FIELDS.items()}


def _origins(exec_config: Mapping[str, Any]) -> dict[str, dict[str, list[str]]]:
    fields = {key: field for field, key in LIST_FIELDS.items()}
    return {fields[key]: {"defaults": list(DEFAULT_EXEC_POLICY_CONFIG[key]),
                          "removed_defaults": [str(item) for item in exec_config.get(removed_key(key)) or []]}
            for key in DEFAULT_ALLOW_KEYS}


def _view(chain: list[str], llm: Mapping[str, Any], exec_config: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "checks": [{**item, "enabled": item["key"] in chain} for item in CHECKS],
        "llm_risk": dict(llm),
        "lists": _lists(exec_config),
        "list_origins": _origins(exec_config),
    }


async def platform_settings(db: AsyncSession) -> dict[str, Any]:
    runtime = await get_agent_runtime_settings(db)
    exec_config = await get_effective_exec_policy_config(db)
    view = _view(list(runtime.get("security_analyzer_chain") or []),
                 {field: runtime.get(key) for field, key in LLM_KEYS.items()}, exec_config)
    view["llm_risk"]["review_model"] = str(runtime.get("security_review_model") or "")
    view["guard_rules"] = [
        {key: rule.get(key) for key in ("id", "label", "description", "category", "action", "severity", "enabled",
                                        "locked")}
        for rule in exec_config.get(AGENT_GUARD_RULES_KEY) or []
    ]
    view["custom_guard_rules"] = [
        {"id": rule.get("id"), "label": rule.get("label") or rule.get("id"), "enabled": rule.get("enabled", True)}
        for rule in exec_config.get(CUSTOM_TOOL_GUARD_RULES_KEY) or []
    ]
    return view


async def _override_row(db: AsyncSession, project_id: str) -> ExecPolicyConfig | None:
    stmt = select(ExecPolicyConfig).where(ExecPolicyConfig.project_id == project_id,
                                          ExecPolicyConfig.name == OVERRIDE_ROW_NAME)
    return (await db.execute(stmt)).scalars().first()


def _bundle(config: Any) -> dict[str, Any]:
    runtime_policy = config.get("runtime_policy") if isinstance(config, Mapping) else None
    bundle = runtime_policy.get("default_bundle") if isinstance(runtime_policy, Mapping) else None
    return dict(bundle) if isinstance(bundle, Mapping) else {}


async def workspace_settings(db: AsyncSession, project: Project) -> dict[str, Any]:
    platform = await platform_settings(db)
    bundle = _bundle(project.config)
    row = await _override_row(db, project.id)
    project_rows = (await db.execute(select(ExecPolicyConfig.id).where(
        ExecPolicyConfig.project_id == project.id, ExecPolicyConfig.is_active))).scalars().all()
    overridden = any(key in bundle for key in ("security_analyzer_chain", *LLM_KEYS.values())) or bool(project_rows)
    chain = bundle.get("security_analyzer_chain") or [item["key"] for item in platform["checks"] if item["enabled"]]
    llm = {field: bundle.get(key, platform["llm_risk"].get(field)) for field, key in LLM_KEYS.items()}
    exec_config = await get_effective_exec_policy_config(db, project_id=project.id)
    effective = _view(list(chain), llm, exec_config)
    return {"mode": "override" if overridden else "inherit", "settings": effective,
            "differences": differences(platform, effective),
            "custom_rows": max(0, len(project_rows) - (1 if row is not None else 0))}


def differences(platform: Mapping[str, Any], effective: Mapping[str, Any]) -> list[str]:
    lines: list[str] = []
    for before, after in zip(platform["checks"], effective["checks"], strict=True):
        if before["enabled"] != after["enabled"]:
            lines.append(f"{after['label']} {'on' if after['enabled'] else 'off'}")
    labels = {"timeout_seconds": "Timeout", "review_threshold": "Ask a person from score",
              "deny_threshold": "Block from score"}
    for field, label in labels.items():
        if platform["llm_risk"].get(field) != effective["llm_risk"].get(field):
            lines.append(f"{label} {effective['llm_risk'].get(field)}")
    for field, values in effective["lists"].items():
        if values != platform["lists"].get(field):
            lines.append(f"{field.replace('_', ' ').capitalize()} list differs")
    return lines


async def workspace_overview(db: AsyncSession) -> list[dict[str, Any]]:
    rows = (await db.execute(select(Project).where(Project.is_active.is_(True)).order_by(Project.name))).scalars()
    overview = []
    for project in rows:
        view = await workspace_settings(db, project)
        overview.append({"id": project.id, "name": project.name, "mode": view["mode"],
                         "differences": view["differences"]})
    return overview
