"""The check proposals' settings per Workspace (``config.check_proposals``) with the platform's defaults (API
contract: threshold 2, approver workspace_owner, all six sources)."""

from __future__ import annotations

from typing import Any

SOURCES = ("review_fixed", "review_change_request", "pr_comment", "pipeline_cause", "revert", "refused_call")
DEFAULTS: dict[str, Any] = {"threshold": 2, "approver_permission": "workspace_owner", "sources": list(SOURCES)}
# Which Workspace roles a permission admits (a role function such as a dedicated ``rules`` role can be added here).
PERMISSION_ROLES = {"workspace_owner": {"owner"}, "workspace_admin": {"owner", "admin"}}


def _valid(key: str, value: Any) -> bool:
    if key == "threshold":
        return type(value) is int and 1 <= value <= 100
    if key == "approver_permission":
        return value in PERMISSION_ROLES
    return isinstance(value, list) and bool(value) and all(item in SOURCES for item in value)


def settings(config: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    own = dict(dict(config or {}).get("check_proposals") or {})
    return {key: ({"value": own[key], "source": "workspace"} if key in own and _valid(key, own[key])
                  else {"value": default, "source": "default"}) for key, default in DEFAULTS.items()}


def value(config: dict[str, Any] | None, key: str) -> Any:
    return settings(config)[key]["value"]


__all__ = ["DEFAULTS", "PERMISSION_ROLES", "SOURCES", "settings", "value"]
