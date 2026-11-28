"""Which tool calls need a person's approval: platform default + per Workspace. The decision itself stays in
``tool_approval.gate``."""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Mapping
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

APPROVAL_POLICY_CONFIG_KEY = "approval_policy"
DEFAULT_CONFIG_KEY = "governance.tool_approval_default"
RISKS: tuple[str, ...] = ("read", "write", "admin", "unknown")
MODE_INHERIT = "inherit"
MODE_ADD = "add"
MODES = (MODE_INHERIT, MODE_ADD)
LIST_KEYS = ("require_for_risks", "require_for_tools", "exempt_tools", "unattended_allowed_tools")
MAX_TOOLS = 200
_TOOL_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:\-]{0,199}$")
EMPTY_POLICY: dict[str, list[str]] = {key: [] for key in LIST_KEYS}

ERROR_INVALID = "tool_approval_policy_invalid"
ERROR_RISK = "tool_approval_risk_unknown"
ERROR_TOOL = "tool_approval_tool_invalid"
ERROR_MODE = "tool_approval_mode_invalid"
AUDIT_DEFAULT = "admin.tool_approvals.default_updated"
AUDIT_WORKSPACE = "admin.tool_approvals.workspace_updated"

logger = logging.getLogger(__name__)


class ToolApprovalPolicyError(ValueError):
    def __init__(self, code: str, path: str) -> None:
        super().__init__(f"{path}: {code}")
        self.code = code
        self.path = path


def normalized_policy(raw: Any, *, path: str = "policy") -> dict[str, list[str]]:
    if raw is None:
        return dict(EMPTY_POLICY)
    if not isinstance(raw, Mapping):
        raise ToolApprovalPolicyError(ERROR_INVALID, path)
    policy: dict[str, list[str]] = {}
    for key in LIST_KEYS:
        value = raw.get(key, [])
        if not isinstance(value, list) or len(value) > MAX_TOOLS:
            raise ToolApprovalPolicyError(ERROR_INVALID, f"{path}.{key}")
        items = list(dict.fromkeys(str(item or "").strip() for item in value if str(item or "").strip()))
        if key == "require_for_risks":
            items = [item.lower() for item in items]
            if any(item not in RISKS for item in items):
                raise ToolApprovalPolicyError(ERROR_RISK, f"{path}.{key}")
        elif any(not _TOOL_PATTERN.match(item) for item in items):
            raise ToolApprovalPolicyError(ERROR_TOOL, f"{path}.{key}")
        policy[key] = items
    return policy


def normalized_workspace_policy(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, Mapping):
        raise ToolApprovalPolicyError(ERROR_INVALID, APPROVAL_POLICY_CONFIG_KEY)
    mode = raw.get("mode")
    if mode not in MODES:
        raise ToolApprovalPolicyError(ERROR_MODE, f"{APPROVAL_POLICY_CONFIG_KEY}.mode")
    if mode == MODE_INHERIT:
        return {"mode": MODE_INHERIT}
    policy = normalized_policy(raw, path=APPROVAL_POLICY_CONFIG_KEY)
    # Unattended runs' allowed writes are the platform's decision only (like exemptions); a Workspace never stores one.
    policy.pop("unattended_allowed_tools", None)
    return {"mode": MODE_ADD, **policy}


_default: dict[str, list[str]] = dict(EMPTY_POLICY)


def platform_default() -> dict[str, list[str]]:
    return {key: list(values) for key, values in _default.items()}


def set_platform_default(policy: Mapping[str, Any]) -> None:
    global _default
    _default = {key: list(policy.get(key) or []) for key in LIST_KEYS}


async def refresh_platform_default(db: AsyncSession) -> dict[str, list[str]]:
    from ..system_config.values import get_system_config_value

    try:
        raw = await get_system_config_value(db, DEFAULT_CONFIG_KEY)
        set_platform_default(normalized_policy(json.loads(raw)) if raw else EMPTY_POLICY)
    except Exception:  # noqa: BLE001 - an unreadable value keeps the last default; logged for the operator
        logger.warning("tool_approval_default_unreadable", exc_info=True)
    return platform_default()


def effective_policy(project_config: Any) -> dict[str, Any]:
    # A Workspace can only add rules: its stored exemptions are ignored, because an exemption waives the default's rules
    # too.
    default = platform_default()
    stored = project_config.get(APPROVAL_POLICY_CONFIG_KEY) if isinstance(project_config, Mapping) else None
    if not isinstance(stored, Mapping) or stored.get("mode") == MODE_INHERIT:
        return {key: values for key, values in default.items() if values}
    merged = {key: list(dict.fromkeys([*default[key], *[str(item) for item in stored.get(key) or []]]))
              for key in ("require_for_risks", "require_for_tools")}
    merged["exempt_tools"] = list(default.get("exempt_tools") or [])
    # Like exemptions, the writes an unattended run may make without a person come from the platform default only.
    merged["unattended_allowed_tools"] = list(default.get("unattended_allowed_tools") or [])
    return {key: values for key, values in merged.items() if values}



async def save_platform_default(db: AsyncSession, raw: Any, *, actor_id: str) -> dict[str, list[str]]:
    from ...models import AuditLog
    from ..system_config.values import set_system_config_value

    policy = normalized_policy(raw)
    before = platform_default()
    await set_system_config_value(
        db, key=DEFAULT_CONFIG_KEY, value=json.dumps(policy) if any(policy.values()) else None,
        description="Tool approvals: platform default",
    )
    db.add(AuditLog(user_id=actor_id, action=AUDIT_DEFAULT, resource_type="system_config",
                    resource_id=DEFAULT_CONFIG_KEY, details={"before": before, "after": policy}))
    await db.flush()
    set_platform_default(policy)
    return policy


async def save_workspace_policy(db: AsyncSession, project: Any, raw: Any, *, actor_id: str) -> dict[str, Any]:
    from ...models import AuditLog
    from ..admin.project.admin_project_config_service import apply_project_config_patch

    policy = normalized_workspace_policy(raw)
    before = (project.config or {}).get(APPROVAL_POLICY_CONFIG_KEY) if isinstance(project.config, Mapping) else None
    await apply_project_config_patch(db, project=project, patch={APPROVAL_POLICY_CONFIG_KEY: policy},
                                     actor_user_id=actor_id)
    db.add(AuditLog(user_id=actor_id, action=AUDIT_WORKSPACE, resource_type="workspace", resource_id=project.id,
                    details={"before": before, "after": policy}))
    await db.flush()
    return policy


__all__ = [
    "APPROVAL_POLICY_CONFIG_KEY",
    "DEFAULT_CONFIG_KEY",
    "MODE_ADD",
    "MODE_INHERIT",
    "RISKS",
    "ToolApprovalPolicyError",
    "effective_policy",
    "normalized_policy",
    "normalized_workspace_policy",
    "platform_default",
    "refresh_platform_default",
    "save_platform_default",
    "save_workspace_policy",
    "set_platform_default",
]
