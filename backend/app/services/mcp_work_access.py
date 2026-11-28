"""Work (secure-work) MCP authorization: OAuth grant binding x workspace scope. Every call is authorized before a
handler touches a business service."""

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
    grant_id: str | None
    # ``None``: the grant is unrestricted (raw ``project_ids`` null); otherwise its project ids.
    binding: frozenset[str] | None
    # ``None``: every Work Item, including workspace-less ones (admin with an unrestricted grant).
    item_project_ids: frozenset[str] | None
    # Projects that list/create may target: membership narrowed by the binding.
    listing_project_ids: frozenset[str]


WorkToolHandler = Callable[..., Awaitable[dict[str, Any]]]


async def resolve_work_grant_binding(db: AsyncSession, *, grant_id: str | None, user_id: str) -> frozenset[str] | None:
    grant = await db.get(OAuthGrant, grant_id) if grant_id else None
    if grant is None or grant.revoked_at is not None or grant.user_id != user_id:
        raise HTTPException(status_code=401, detail=INVALID_GRANT_DETAIL)
    # The raw binding: ``None`` is unrestricted, ``[]`` grants no Workspace, malformed refuses. The shared token-context
    # projection collapses ``[]`` and malformed to unrestricted, which would widen Work access.
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
    # Out of scope answers like a missing item; several matches are a conflict, never an arbitrary pick.
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
    # Out of scope is the same 404 as missing.
    text = str(change_plan_id or "").strip()
    plan = await db.get(WorkChangePlan, text) if text else None
    item = await db.get(WorkItem, plan.work_item_id) if plan is not None else None
    if item is None or not work_item_in_scope(_item_scope(scope), item):
        raise HTTPException(status_code=404, detail="Change Plan not found")
    return plan


def require_listing_project(scope: WorkGrantScope, project_id: str) -> None:
    if project_id not in scope.listing_project_ids:
        raise HTTPException(status_code=403, detail="User is not allowed to access this project")



def grant_scope_audit(scope: WorkGrantScope | None) -> dict[str, Any]:
    # Never tokens.
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
    # The denial commit carries only the MCP audit row.
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
    # Every authorization refusal is raised before a business service runs; the audit records the raw resolved binding.
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
