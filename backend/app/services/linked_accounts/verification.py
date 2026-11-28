"""A Workspace connection confirms a linked account, or finds an Atlassian account by email."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ...models import User, UserLinkedAccount
from ...tools.context import ToolContext
from ..access_control import WORKSPACE_NOT_FOUND_MESSAGE
from ..named_connections.descriptors import descriptor_for_tool
from ..named_connections.route_plan import CONNECTION_PARAM
from ..named_connections.service_config import usable_connection_ids
from ..project.service import get_project_config
from ..run_capability.declared import SOURCE_FLOW_DEFINITION, declared_run_capability
from .contract import (
    ATLASSIAN,
    BITBUCKET_SERVER,
    JIRA_SERVER,
    PLATFORMS,
    STATUS_FAILED,
    STATUS_VERIFIED,
    LinkedAccountError,
)
from .store import identifier_of, mark_verification


@dataclass(slots=True)
class Lookup:
    tool: str
    reachable: bool
    users: list[dict[str, Any]]
    error: str = ""


async def _scope_check(db: AsyncSession, actor: User, project_id: str) -> None:
    from ..secure_work.access import work_scope_project_ids

    if not str(project_id or "").strip():
        raise LinkedAccountError("workspace_required", "Choose the Workspace whose connection checks the account.")
    scope = await work_scope_project_ids(db, actor)
    if scope is not None and project_id not in scope:
        # The answer of an unknown Workspace: an outsider never learns whether a Workspace exists.
        raise LinkedAccountError("project_not_found", WORKSPACE_NOT_FOUND_MESSAGE, 404)


async def _context(db: AsyncSession, actor: User, project_id: str) -> ToolContext:
    return ToolContext(
        user_id=actor.id, project_ids=[project_id], roles=[], session_id=f"linked-account-{uuid.uuid4().hex[:12]}",
        project_config=await get_project_config(project_id, db), db=db,
        run_capability=declared_run_capability(None, source=SOURCE_FLOW_DEFINITION).tool_context_state(),
    )


async def _lookup(context: ToolContext, tool: str, arguments: dict[str, Any]) -> Lookup:
    from ...tools.registry import execute_tool_with_plugins

    try:
        from ..content_security.knowledge_fence import unfenced_result

        result = unfenced_result(await execute_tool_with_plugins(tool, arguments, context))
    except Exception as error:  # a connection that cannot answer is no verdict on the account
        return Lookup(tool, False, [], f"{type(error).__name__}")
    payload = result if isinstance(result, dict) else {}
    if payload.get("approval_required"):
        return Lookup(tool, False, [], "the Workspace's tool approval policy holds this lookup for an approval")
    if payload.get("error") or str(payload.get("status") or "").lower() in {"error", "denied", "blocked", "failed"}:
        error = payload.get("error")
        text = error.get("message") if isinstance(error, dict) else error
        return Lookup(tool, False, [], str(text or payload.get("status") or "the lookup failed")[:300])
    return Lookup(tool, True, [item for item in payload.get("users") or [] if isinstance(item, dict)])


async def _lookups(context: ToolContext, tool: str, arguments: dict[str, Any]) -> list[Lookup]:
    descriptor = descriptor_for_tool(tool)
    connections = usable_connection_ids(descriptor.connector, context.project_config) if descriptor else []
    if not connections:  # none with a target: the router answers why (not configured, refused, ...)
        return [await _lookup(context, tool, arguments)]
    return [await _lookup(context, tool, {**arguments, CONNECTION_PARAM: connection}) for connection in connections]


def _matches(platform_key: str, identifier: str, user: dict[str, Any]) -> bool:
    if platform_key == ATLASSIAN:
        return identifier in (user.get("account_id"), user.get("uuid"))
    wanted = identifier.lower()
    return any(str(user.get(key) or "").lower() == wanted for key in ("name", "key", "slug"))


def _plan(platform_key: str, identifier: str) -> list[tuple[str, dict[str, Any]]]:
    if platform_key == ATLASSIAN:
        return [("search_jira_users", {"account_id": identifier}),
                ("search_bitbucket_users", {"account_id": identifier})]
    if platform_key == JIRA_SERVER:
        return [("search_jira_users", {"query": identifier, "limit": 50})]
    if platform_key == BITBUCKET_SERVER:
        return [("search_bitbucket_users", {"query": identifier, "limit": 50})]
    return []


async def verify_account(db: AsyncSession, row: UserLinkedAccount, *, project_id: str, actor: User) -> dict[str, Any]:
    plan = _plan(row.platform, identifier_of(row))
    label = PLATFORMS[row.platform].label
    if not plan:
        raise LinkedAccountError("not_verifiable", f"The {label} connection offers no account lookup; the account is "
                                 "used as entered and the SCM reports an unknown reviewer.", 409)
    await _scope_check(db, actor, project_id)
    context = await _context(db, actor, project_id)
    errors: list[str] = []
    for tool, arguments in plan:
        lookups = await _lookups(context, tool, arguments)
        reachable = [lookup for lookup in lookups if lookup.reachable]
        if not reachable:
            errors.extend(f"{tool}: {lookup.error}" for lookup in lookups)
            continue
        users = [user for lookup in reachable for user in lookup.users]
        found = next((user for user in users if _matches(row.platform, identifier_of(row), user)), None)
        status = STATUS_VERIFIED if found is not None else STATUS_FAILED
        detail = (f"{label} knows this account" if found is not None
                  else f"the Workspace's connection ({tool}) does not know this account")
        mark_verification(db, row, status=status, detail=detail, via=tool, project_id=project_id, actor_id=actor.id,
                          display_name=(found or {}).get("display_name"))
        await db.flush()
        return {"status": status, "detail": detail, "via": tool}
    raise LinkedAccountError("needs_configuration", f"This Workspace has no connection that can check a {label} "
                             f"account ({'; '.join(errors)[:400]}).", 409)


async def find_atlassian_account_by_email(
    db: AsyncSession, *, email: str, project_id: str, actor: User
) -> dict[str, Any]:
    await _scope_check(db, actor, project_id)
    address = str(email or "").strip()
    if "@" not in address:
        raise LinkedAccountError("invalid_email", "Enter the email address of the Atlassian account.")
    lookups = await _lookups(await _context(db, actor, project_id), "search_jira_users", {"email": address})
    reachable = [lookup for lookup in lookups if lookup.reachable]
    if not reachable:
        errors = "; ".join(lookup.error for lookup in lookups)[:400]
        raise LinkedAccountError("needs_configuration", "Finding an Atlassian account by email needs the Workspace's "
                                 f"Jira Cloud connection ({errors}).", 409)
    accounts: dict[str, dict[str, Any]] = {}
    for lookup in reachable:
        if len([user for user in lookup.users if user.get("account_id")]) > 1:
            raise _not_single()
        for user in lookup.users:
            if user.get("account_id"):
                accounts.setdefault(str(user["account_id"]), user)
    if len(accounts) > 1:
        raise LinkedAccountError("account_ambiguous", "The Workspace's Jira connections know different Atlassian "
                                 "accounts with this email; link the account by its account id.", 409)
    if not accounts:
        raise _not_single()
    account_id, account = next(iter(accounts.items()))
    return {"account_id": account_id, "display_name": account.get("display_name"), "via": "search_jira_users"}


def _not_single() -> LinkedAccountError:
    return LinkedAccountError("account_not_found", "No single Atlassian account shows this email (an account that "
                              "hides its email is linked by its account id).", 404)


__all__ = ["find_atlassian_account_by_email", "verify_account"]
