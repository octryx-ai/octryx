"""Work (secure-work) MCP authorization: OAuth grant binding x workspace scope.

The secure-work tool family runs under the user-consented ``work:manage`` scope. Every call is
authorized here before a handler touches a business service:

- the grant row is re-read and its *raw* ``project_ids`` validated. The shared resource context
  collapses ``[]`` and malformed values to "unrestricted"; Work does not inherit that:
  ``None`` is the documented unrestricted binding, ``[]`` an empty scope, anything else that is
  not a list of non-blank strings refuses authentication (401);
- item scope = the workspace scope (``work_scope_project_ids``: admin cross-workspace,
  otherwise direct/group membership) intersected with the binding. An admin crosses workspaces
  only inside a bound grant's projects, and a bound grant never reaches workspace-less items;
- list/create scope = membership (no admin bypass) intersected with the binding;
- item, key and plan references resolve only inside the scope; out of scope answers like a
  missing reference, and a key matching several in-scope items is an explicit 409;
- secondary configuration targets (``mcp_work_targets``; workflow definitions: supplied, stored on a plan, or the
  default, including the one a coding start transitions through; repository profiles, supplied or
  stored on the selected change units, and the code repository they wrap) must be owned by the
  Work Item's own workspace or be explicitly global (``project_id`` is ``None``). A global profile may not
  wrap another workspace's code repository. Incompatible targets answer exactly like missing
  ones and are refused before the service, so nothing is read from or written for them.

Shared OAuth, knowledge and gateway consumers keep their existing binding semantics.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import User, WorkChangePlan, WorkItem
from ..models.security.oauth_provider import OAuthGrant
from .mcp_auto_session import record_mcp_tool_activity
from .mcp_knowledge_observability import audit_mcp_knowledge_tool_call, enforce_mcp_knowledge_rate_limit
from .project import get_user_project_ids
from .secure_work.access import work_item_in_scope, work_scope_project_ids

WORK_MCP_SCOPE = "work:manage"
INVALID_GRANT_DETAIL = "OAuth grant is not valid for Work tools"
_AUDIT_ID_LIMIT = 20


@dataclass(frozen=True)
class WorkGrantScope:
    """The resolved authority of one secure-work MCP call."""

    grant_id: str | None
    # ``None``: the grant is unrestricted (raw ``project_ids`` null); otherwise its project ids.
    binding: frozenset[str] | None
    # ``None``: every Work Item, including workspace-less ones (admin with an unrestricted grant).
    item_project_ids: frozenset[str] | None
    # Projects that list/create may target: membership narrowed by the binding.
    listing_project_ids: frozenset[str]


WorkToolHandler = Callable[..., Awaitable[dict[str, Any]]]


async def resolve_work_grant_binding(db: AsyncSession, *, grant_id: str | None, user_id: str) -> frozenset[str] | None:
    """Re-read the grant and validate its raw project binding; 401 when unusable."""
    grant = await db.get(OAuthGrant, grant_id) if grant_id else None
    if grant is None or grant.revoked_at is not None or grant.user_id != user_id:
        raise HTTPException(status_code=401, detail=INVALID_GRANT_DETAIL)
    raw = grant.project_ids
    if raw is None:
        return None
    if not isinstance(raw, list):
        raise HTTPException(status_code=401, detail=INVALID_GRANT_DETAIL)
    project_ids: set[str] = set()
    for entry in raw:
        if not isinstance(entry, str) or not entry.strip():
            raise HTTPException(status_code=401, detail=INVALID_GRANT_DETAIL)
        project_ids.add(entry.strip())
    return frozenset(project_ids)


async def build_work_grant_scope(
    db: AsyncSession, *, user: User, grant_id: str | None, binding: frozenset[str] | None
) -> WorkGrantScope:
    """Intersect the user's workspace scope and membership with an already validated binding."""
    user_scope = await work_scope_project_ids(db, user)
    membership = user_scope if user_scope is not None else set(await get_user_project_ids(user.id, db))
    if binding is None:
        item_scope = None if user_scope is None else frozenset(user_scope)
        listing = frozenset(membership)
    else:
        item_scope = binding if user_scope is None else frozenset(user_scope & binding)
        listing = frozenset(membership & binding)
    return WorkGrantScope(grant_id=grant_id, binding=binding, item_project_ids=item_scope, listing_project_ids=listing)


async def resolve_work_grant_scope(db: AsyncSession, *, user: User, grant_id: str | None) -> WorkGrantScope:
    binding = await resolve_work_grant_binding(db, grant_id=grant_id, user_id=user.id)
    return await build_work_grant_scope(db, user=user, grant_id=grant_id, binding=binding)


def _item_scope(scope: WorkGrantScope) -> set[str] | None:
    return None if scope.item_project_ids is None else set(scope.item_project_ids)


async def scoped_work_item(db: AsyncSession, scope: WorkGrantScope, value: Any) -> WorkItem:
    """Resolve a Work Item by id or source key inside ``scope``.

    Out of scope answers exactly like a missing item; a key that matches several in-scope items
    is an explicit conflict instead of an arbitrary pick.
    """
    text = str(value or "").strip()
    if not text:
        raise HTTPException(status_code=422, detail="work_item (source key or id) is required")
    item_scope = _item_scope(scope)
    item = await db.get(WorkItem, text)
    if item is not None and work_item_in_scope(item_scope, item):
        return item
    stmt = select(WorkItem).where(WorkItem.source_key == text)
    if item_scope is not None:
        stmt = stmt.where(WorkItem.project_id.in_(sorted(item_scope)))
    matches = (await db.execute(stmt.limit(2))).scalars().all()
    if not matches:
        raise HTTPException(status_code=404, detail=f"Work item not found: {text}")
    if len(matches) > 1:
        raise HTTPException(status_code=409, detail=f"Work item key is ambiguous: {text}; use the work item id")
    return matches[0]


async def scoped_change_plan(db: AsyncSession, scope: WorkGrantScope, change_plan_id: Any) -> WorkChangePlan:
    """A Change Plan whose owning Work Item is in ``scope``; out of scope is the same 404 as missing."""
    text = str(change_plan_id or "").strip()
    plan = await db.get(WorkChangePlan, text) if text else None
    item = await db.get(WorkItem, plan.work_item_id) if plan is not None else None
    if item is None or not work_item_in_scope(_item_scope(scope), item):
        raise HTTPException(status_code=404, detail="Change Plan not found")
    return plan


def require_listing_project(scope: WorkGrantScope, project_id: str) -> None:
    """List/create targets: membership narrowed by the binding (plain 403 shape)."""
    if project_id not in scope.listing_project_ids:
        raise HTTPException(status_code=403, detail="User is not allowed to access this project")



def grant_scope_audit(scope: WorkGrantScope | None) -> dict[str, Any]:
    """Audit metadata for the call's grant scope: mode and bounded project ids, never tokens."""
    if scope is None:
        return {"binding_mode": "unresolved"}
    if scope.binding is None:
        metadata: dict[str, Any] = {"binding_mode": "unrestricted"}
    else:
        metadata = {
            "binding_mode": "bound" if scope.binding else "empty",
            "binding_count": len(scope.binding),
            "binding_project_ids": sorted(scope.binding)[:_AUDIT_ID_LIMIT],
        }
    items = scope.item_project_ids
    metadata["item_scope"] = "all" if items is None else {"count": len(items)}
    return metadata


def _audit_project(scope: WorkGrantScope | None) -> str | None:
    """The audit's ``api_key_project_id`` column: the bound project ids, only for a non-empty binding."""
    if scope is None or not scope.binding:
        return None
    return ",".join(sorted(scope.binding)[:_AUDIT_ID_LIMIT])


async def _audit_refusal(
    db: AsyncSession,
    *,
    user: User,
    grant_id: str | None,
    scope: WorkGrantScope | None,
    tool_name: str,
    arguments: dict[str, Any],
    exc: HTTPException,
) -> None:
    """The denial commit: only the MCP audit row, with the scope as far as it was resolved."""
    status_value = "rate_limited" if exc.status_code == 429 else "error"
    await audit_mcp_knowledge_tool_call(
        db,
        user_id=user.id,
        api_key_id=grant_id,
        api_key_project_id=_audit_project(scope),
        tool_name=tool_name,
        arguments=arguments,
        status_value=status_value,
        error_detail=str(exc.detail or ""),
        transport="mcp",
        grant_scope=grant_scope_audit(scope),
    )
    await db.commit()


async def _record_success(
    db: AsyncSession,
    *,
    user: User,
    grant_id: str | None,
    client_name: str,
    scope: WorkGrantScope | None,
    tool_name: str,
    arguments: dict[str, Any],
) -> None:
    await record_mcp_tool_activity(
        db,
        user=user,
        grant_id=grant_id,
        client_name=client_name,
        tool_name=tool_name,
        arguments=arguments,
    )
    await audit_mcp_knowledge_tool_call(
        db,
        user_id=user.id,
        api_key_id=grant_id,
        api_key_project_id=_audit_project(scope),
        tool_name=tool_name,
        arguments=arguments,
        result={"status": "ok"},
        status_value="success",
        transport="mcp",
        grant_scope=grant_scope_audit(scope),
    )
    await db.commit()


async def run_secure_work_tool(
    db: AsyncSession,
    *,
    handlers: Mapping[str, WorkToolHandler],
    user_id: str,
    grant_id: str | None,
    client_name: str,
    tool_name: str,
    arguments: dict[str, Any],
    resolve_scope: Callable[[AsyncSession, User], Awaitable[WorkGrantScope]] | None = None,
) -> dict[str, Any]:
    """Authorize and run one secure-work tool: rate limit, grant scope, handler, audit, commit.

    ``resolve_scope``: a narrower authority than the grant's ``work:manage`` (a run-bound session's own run board,
    ``mcp_run_board``); the rate limit, the audit row and the commit stay the same.

    Every authorization refusal is raised before the handler reaches a business service, so the
    denial commit carries only the MCP audit row. The audit records the *raw* resolved binding
    (unrestricted, empty and bound stay distinct), never the lossy token-context projection.
    """
    user = await db.get(User, user_id)
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="MCP OAuth user is not active")
    scope: WorkGrantScope | None = None
    try:
        await enforce_mcp_knowledge_rate_limit(api_key_id=grant_id, user_id=user_id, tool_name=tool_name)
        scope = (await resolve_scope(db, user) if resolve_scope is not None
                 else await resolve_work_grant_scope(db, user=user, grant_id=grant_id))
        result = await handlers[tool_name](db, user=user, scope=scope, arguments=arguments)
    except HTTPException as exc:
        await _audit_refusal(
            db, user=user, grant_id=grant_id, scope=scope, tool_name=tool_name, arguments=arguments, exc=exc
        )
        raise
    await _record_success(
        db, user=user, grant_id=grant_id, client_name=client_name, scope=scope, tool_name=tool_name,
        arguments=arguments,
    )
    return result


__all__ = [
    "INVALID_GRANT_DETAIL",
    "WORK_MCP_SCOPE",
    "WorkGrantScope",
    "build_work_grant_scope",
    "grant_scope_audit",
    "require_listing_project",
    "resolve_work_grant_binding",
    "resolve_work_grant_scope",
    "run_secure_work_tool",
    "scoped_change_plan",
    "scoped_work_item",
]
