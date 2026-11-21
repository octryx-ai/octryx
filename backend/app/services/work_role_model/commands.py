"""Per-role phase shell rules, layered on the Workspace's Command safety.

"Too much security blocks the system": an admin widens or narrows what a workflow phase may run per role instead of
fixed refusals. A role ``deny`` pattern refuses (naming the role setting); a role ``allow`` pattern admits a command
the phase's strict shell would refuse. The platform's short hard-deny list (``shell_rules.hard_denied``, checked
first) and the Workspace's always-blocked patterns (``capability_decision``, checked after) still win. Patterns are
globs over the whole command (``npm run *``); deny wins over allow, across all of the person's roles.
"""
from __future__ import annotations

import fnmatch
from typing import Any

ALLOW_KEY, DENY_KEY, ROLES_KEY = "work_role_command_allow", "work_role_command_deny", "work_role_names"


def with_role_commands(exec_config: dict[str, Any], grant: Any) -> dict[str, Any]:
    """``exec_config`` plus the grant's command rules (unchanged when nothing narrows or widens)."""
    if grant is None or grant.unrestricted or not (grant.command_allow or grant.command_deny):
        return exec_config
    return {**exec_config, ALLOW_KEY: list(grant.command_allow), DENY_KEY: list(grant.command_deny),
            ROLES_KEY: [role.name for role in grant.roles]}


def _matches(command: str, patterns: Any) -> str | None:
    text = " ".join(command.split())
    return next((str(p) for p in patterns or [] if fnmatch.fnmatchcase(text, " ".join(str(p).split()))), None)


def role_command_denial(command: str, exec_config: dict[str, Any] | None) -> str | None:
    """The refusal text when one of the person's roles denies ``command``, else ``None``."""
    config = exec_config or {}
    pattern = _matches(command, config.get(DENY_KEY))
    if pattern is None:
        return None
    roles = ", ".join(config.get(ROLES_KEY) or [])
    return (f"Your work role ({roles}) does not run '{pattern}' in workflow phases. A Workspace admin can change the "
            "role's command rules (Workspace › Roles).")


def role_command_allowed(command: str, exec_config: dict[str, Any] | None) -> bool:
    config = exec_config or {}
    return _matches(command, config.get(ALLOW_KEY)) is not None and role_command_denial(command, config) is None


__all__ = ["ALLOW_KEY", "DENY_KEY", "role_command_allowed", "role_command_denial", "with_role_commands"]
