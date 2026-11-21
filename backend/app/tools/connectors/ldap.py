"""LDAP connector tools."""

from __future__ import annotations

from ..context import ToolContext
from .common import _limit, _normalize_string_list, _string
from .ldap_core import (
    _escape_ldap_filter,
    _ldap_group_base_dn,
    _ldap_group_filter,
    _ldap_group_name_attribute,
    _ldap_membership_attribute,
    _ldap_search,
    _normalize_ldap_group,
    _search_ldap_users,
)
from .ldap_sync import _sync_local_users_from_ldap


class SearchLdapUserTool:
    name = "search_user"
    description = "Search users in LDAP or Active Directory."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, object]:
        result = await _search_ldap_users(
            context,
            query=_string(params.get("query") or params.get("username") or params.get("email")),
            limit=_limit(context, params, default=20, maximum=200),
            timeout=int(params.get("timeout_sec") or 30),
        )
        if result.get("error"):
            return result
        return {"count": result["count"], "users": result["users"], "base_dn": result["base_dn"]}


class GetLdapGroupsTool:
    name = "get_groups"
    description = "List LDAP groups or the groups of a specific user."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, object]:
        username = _string(params.get("username"))
        user_dn = _string(params.get("user_dn"))
        group_filter = _ldap_group_filter(context)
        membership_attr = _ldap_membership_attribute(context)
        if username or user_dn:
            if not user_dn:
                user_search = await _search_ldap_users(
                    context, query=username, limit=5, timeout=int(params.get("timeout_sec") or 30)
                )
                if user_search.get("error"):
                    return user_search
                matched = next((item for item in user_search["users"] if item.get("username") == username), None) or (
                    user_search["users"][0] if user_search["users"] else None
                )
                if matched is None:
                    return {"error": f"User '{username}' was not found in LDAP"}
                user_dn = _string(matched.get("dn"))
                username = _string(matched.get("username"))
            membership_value = username if membership_attr.lower() == "memberuid" else user_dn
            search_filter = f"(&{group_filter}({membership_attr}={_escape_ldap_filter(membership_value)}))"
        else:
            search_filter = group_filter
        result = await _ldap_search(
            context,
            base_dn=_ldap_group_base_dn(context),
            filter_expr=search_filter,
            attrs=[_ldap_group_name_attribute(context), membership_attr, "cn"],
            limit=_limit(context, params, default=50, maximum=200),
            timeout=int(params.get("timeout_sec") or 30),
        )
        if result.get("error"):
            return result
        groups = [_normalize_ldap_group(entry, context) for entry in result["entries"]]
        return {"count": len(groups), "groups": groups, "base_dn": result["base_dn"], "user_dn": user_dn}


class CheckLdapMembershipTool:
    name = "check_membership"
    description = "Check whether a specific LDAP user belongs to a group."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, object]:
        username = _string(params.get("username"))
        group_name = _string(params.get("group_name"))
        group_dn = _string(params.get("group_dn"))
        if not username:
            return {"error": "username is required"}
        if not group_name and not group_dn:
            return {"error": "group_name or group_dn is required"}
        result = await GetLdapGroupsTool().execute(
            {"username": username, "timeout_sec": params.get("timeout_sec")}, context
        )
        if result.get("error"):
            return result
        matched = next(
            (
                group
                for group in result.get("groups", [])
                if (group_name and _string(group.get("name")).lower() == group_name.lower())
                or (group_dn and _string(group.get("dn")).lower() == group_dn.lower())
            ),
            None,
        )
        return {
            "username": username,
            "group_name": group_name or (_string(matched.get("name")) if matched else ""),
            "group_dn": group_dn or (_string(matched.get("dn")) if matched else ""),
            "is_member": matched is not None,
        }


class SyncLdapUsersTool:
    name = "sync_users"
    description = "Sync users from LDAP or Active Directory into the local Octryx user store."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, object]:
        result = await _search_ldap_users(
            context,
            query=_string(params.get("query")),
            limit=_limit(context, params, default=50, maximum=500),
            timeout=int(params.get("timeout_sec") or 60),
        )
        if result.get("error"):
            return result
        payload: dict[str, object] = {"count": result["count"], "users": result["users"]}
        if bool(params.get("persist_local_users") or params.get("create_local_users")):
            synced = await _sync_local_users_from_ldap(
                context, result["users"], role_names=_normalize_string_list(params.get("roles")) or ["viewer"]
            )
            if synced.get("error"):
                return synced
            payload.update(synced)
        return payload


class LdapUserProvisioningTool:
    name = "user_provisioning"
    description = "Provision or update a local Octryx user from LDAP data for onboarding workflows."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, object]:
        query = _string(params.get("username") or params.get("email") or params.get("query"))
        if not query:
            return {"error": "username, email or query is required"}
        result = await _search_ldap_users(context, query=query, limit=10, timeout=int(params.get("timeout_sec") or 30))
        if result.get("error"):
            return result
        matched = next(
            (item for item in result["users"] if query in {_string(item.get("username")), _string(item.get("email"))}),
            None,
        ) or (result["users"][0] if result["users"] else None)
        if matched is None:
            return {"error": f"No LDAP user matched '{query}'"}
        synced = await _sync_local_users_from_ldap(
            context, [matched], role_names=_normalize_string_list(params.get("roles")) or ["viewer"]
        )
        if synced.get("error"):
            return synced
        return {
            "status": "provisioned",
            "ldap_user": matched,
            "local_user": synced["synced_users"][0] if synced.get("synced_users") else {},
            "created_count": synced.get("created_count", 0),
            "updated_count": synced.get("updated_count", 0),
        }
