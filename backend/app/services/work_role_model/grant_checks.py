"""Synchronous checks against a computed grant, and refusals that name the setting and who can change it.

"Every refusal names the setting and who can change it." No role means no permission, and an admin can assign one —
no role means no tools, with a clear reason instead of a silent empty surface.
"""
from __future__ import annotations

from typing import Any

from .effective import WorkRoleGrant

POLICY = "work_role"
CODE_NO_ROLE = "work_role_none"
CODE_TOOL = "role_tool_not_granted"
CODE_CONNECTION = "role_connection_not_granted"
CODE_PO = "po_function_required"
WHO_CAN_CHANGE = "a Workspace admin (Workspace › Roles)"

NO_ROLE_EN = ("You have no role in this Workspace, so no tools are available. A Workspace admin can assign one "
              "(Workspace › Roles).")
#: Meta tools that come with any role (the chat's deferred-tool loader); never with no role.
# Gateways whose inner calls are filtered by name: ``tool_search`` loads tools, the device's ``rest_operations`` /
# ``rest_call`` list and run ``rest__`` operations, each checked against the roles like a chat call.
ROLE_META_TOOLS = frozenset({"tool_search", "rest_operations", "rest_call"})


def empty_reason(grant: WorkRoleGrant) -> str | None:
    return NO_ROLE_EN if not grant.unrestricted and not grant.roles else None


def _role_names(grant: WorkRoleGrant) -> str:
    return ", ".join(role.name for role in grant.roles)


def tool_allowed(grant: WorkRoleGrant | None, tool_name: str) -> bool:
    if grant is None or grant.unrestricted:
        return True
    if not grant.roles:
        return False
    return tool_name in ROLE_META_TOOLS or grant.allows_tool(tool_name)


def tool_refusal(grant: WorkRoleGrant | None, tool_name: str) -> dict[str, Any] | None:
    """``None`` when the grant admits the tool, else the refusal payload (chat dispatch and MCP calls)."""
    if tool_allowed(grant, tool_name):
        return None
    assert grant is not None
    if not grant.roles:
        return {"error": NO_ROLE_EN, "message": NO_ROLE_EN, "code": CODE_NO_ROLE, "state": "needs_configuration",
                "tool_name": tool_name,
                "policy": POLICY, "setting": "a role assignment in this Workspace", "who_can_change": WHO_CAN_CHANGE}
    message = (f"Your roles in this Workspace ({_role_names(grant)}) do not include the tool '{tool_name}'. "
               f"It needs a role with a function whose tool set contains it; {WHO_CAN_CHANGE} can assign such a "
               "role or add the tool to a function.")
    return {"error": message, "message": message, "code": CODE_TOOL, "state": "needs_configuration",
            "tool_name": tool_name, "policy": POLICY,
            "roles": [role.key for role in grant.roles],
            "setting": "role functions / function tool set", "who_can_change": WHO_CAN_CHANGE}


def connection_refusal(grant: WorkRoleGrant | None, tool_name: str, connection_id: str | None,
                       connection_label: str = "") -> dict[str, Any] | None:
    """A write through a connection none of the person's delivery roles is granted (delivery per connection)."""
    if grant is None or grant.allows_connection(connection_id):
        return None
    label = connection_label or connection_id or "the default connection"
    message = (f"Your roles in this Workspace ({_role_names(grant)}) may not write through the connection "
               f"'{label}'. {WHO_CAN_CHANGE[0].upper()}{WHO_CAN_CHANGE[1:]} can grant it in the role's delivery "
               "connections.")
    return {"error": message, "message": message, "code": CODE_CONNECTION, "state": "needs_configuration",
            "tool_name": tool_name, "policy": POLICY,
            "connection_id": connection_id, "setting": "role › delivery connections",
            "who_can_change": WHO_CAN_CHANGE}


def filter_tool_names(grant: WorkRoleGrant | None, names: list[str]) -> list[str]:
    return [name for name in names if tool_allowed(grant, name)]


def grant_view(grant: WorkRoleGrant, tool_names: list[str] | None = None, *,
               function_names: dict[str, str] | None = None,
               connection_names: dict[str, str]) -> dict[str, Any]:
    """The API shape of ``EffectivePermission``, with display names for functions and connections.

    ``connection_names`` holds the connections available in the grant's Workspace (``catalog_scope``); a role's stored
    connection outside it is not serialized, neither as id nor as name."""
    tools = sorted(name for name in (tool_names or []) if grant.unrestricted or tool_allowed(grant, name))
    selected = grant.write_connections
    write = None if selected is None else sorted(cid for cid in selected if cid in connection_names)
    return {
        "workspace_id": grant.workspace_id, "user_id": grant.user_id, "enforced": grant.enforced,
        "platform_admin": grant.platform_admin,
        "roles": [{"id": role.id, "key": role.key, "name": role.name, "trusted": role.trusted, "via": list(role.via)}
                  for role in grant.roles],
        "functions": sorted(grant.functions), "tools": tools, "tool_entries": list(grant.entries),
        "functions_detail": [{"key": key, "name": (function_names or {}).get(key, key)}
                             for key in sorted(grant.functions)],
        "write_connections": "all" if write is None else write,
        "write_connections_detail": None if write is None else [
            {"id": cid, "name": connection_names[cid]} for cid in write],
        "trusted": grant.trusted,
        "command_policy": {"allow": list(grant.command_allow), "deny": list(grant.command_deny)},
        "empty_reason": empty_reason(grant),
    }


__all__ = ["CODE_CONNECTION", "CODE_NO_ROLE", "CODE_PO", "CODE_TOOL", "NO_ROLE_EN", "POLICY",
           "ROLE_META_TOOLS", "WHO_CAN_CHANGE", "connection_refusal", "empty_reason", "filter_tool_names",
           "grant_view", "tool_allowed", "tool_refusal"]
