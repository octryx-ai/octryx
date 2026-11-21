"""Secure-work tool handlers for the MCP protocol server.

Exposes the governed delivery lifecycle to external MCP clients (Claude
Code and peers) under the ``work:manage`` OAuth scope: find work items,
plan change units, generate and decide change plans (the acceptance-coverage
gate applies unchanged), redeclare after a declined PR, start the coding
agent, transition the lifecycle (Jira write-back applies), and read the
coding observability summary. Every handler is a thin adapter over the same
services the REST routes use - no separate code path, same gates, same audit.

Work access boundary (``mcp_work_access``). The ``work:manage`` scope is
user-consented, so it is not a role, and the dispatcher hands every handler the call's
``WorkGrantScope`` (OAuth grant binding x workspace scope):

- item, key and plan references resolve only inside the scope (non-disclosing 404, explicit
  409 for an ambiguous key) before any business service runs;
- change-plan generate/decide/redeclare, change units planning, coding agent start and lifecycle
  transition first require the platform work-operator role, like the REST routes;
- list and create stay membership-only (no admin bypass), narrowed by the grant binding;
- session linking validates the secondary session: the caller's own, in the item's workspace;
- secondary configuration (supplied, stored or default workflow; repository profiles and their
  code repository) must belong to the item's workspace or be explicitly global, checked before
  the service (``mcp_work_access``).
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ..models import User
from .mcp_work_access import WorkGrantScope, require_listing_project, scoped_change_plan, scoped_work_item
from .mcp_work_item_listing import mcp_work_item_list
from .mcp_work_targets import (
    require_coding_start_targets,
    require_compatible_repository_profiles,
    require_payload_workflow_compatible,
    require_plan_workflow_compatible,
    transition_workflow_id,
)
from .secure_work import (
    decide_change_plan,
    generate_change_plan,
    get_work_item_coding_observability,
    plan_work_item_change_units,
    redeclare_work_item,
    start_work_item_coding_agent_execution,
)
from .secure_work.access import require_work_operator
from .secure_work.platform_item_context import build_work_item_context
from .secure_work.platform_item_sessions import link_validated_session_to_work_item, resolve_linkable_session
from .secure_work.platform_items import add_work_item_note, create_platform_work_item
from .secure_work.serializers import serialize_work_item
from .secure_work.workflow_mapping import transition_work_item


async def mcp_work_item_find(
    db: AsyncSession, *, user: User, scope: WorkGrantScope, arguments: dict[str, Any]
) -> dict[str, Any]:
    item = await scoped_work_item(db, scope, arguments.get("work_item") or arguments.get("source_key"))
    serialized = serialize_work_item(item)
    return {
        key: serialized.get(key)
        for key in (
            "id",
            "source_key",
            "title",
            "work_state",
            "source_status",
            "source_url",
            "project_id",
            "assignee",
            "priority",
        )
    }


async def mcp_change_units_plan(
    db: AsyncSession, *, user: User, scope: WorkGrantScope, arguments: dict[str, Any]
) -> dict[str, Any]:
    await require_work_operator(db, user)
    item = await scoped_work_item(db, scope, arguments.get("work_item"))
    # The service replaces the active units before it reads profiles: check them first.
    await require_compatible_repository_profiles(db, item, arguments.get("units"))
    result = await plan_work_item_change_units(
        db,
        work_item_id=item.id,
        current_user=user,
        payload={"units": arguments.get("units") or []},
    )
    return {"work_item_id": item.id, "units": result.get("items", [])}


async def mcp_change_plan_generate(
    db: AsyncSession, *, user: User, scope: WorkGrantScope, arguments: dict[str, Any]
) -> dict[str, Any]:
    await require_work_operator(db, user)
    item = await scoped_work_item(db, scope, arguments.get("work_item"))
    payload = dict(arguments.get("payload") or {})
    await require_payload_workflow_compatible(db, item, payload.get("workflow_id"))
    plan = await generate_change_plan(
        db,
        work_item_id=item.id,
        current_user=user,
        payload=payload,
    )
    return {
        key: plan.get(key)
        for key in ("id", "version", "status", "acceptance_criteria", "validation_plan", "open_questions")
    }


async def mcp_change_plan_decide(
    db: AsyncSession, *, user: User, scope: WorkGrantScope, arguments: dict[str, Any]
) -> dict[str, Any]:
    await require_work_operator(db, user)
    plan = await scoped_change_plan(db, scope, arguments.get("change_plan_id"))
    await require_plan_workflow_compatible(db, plan)
    result = await decide_change_plan(
        db,
        change_plan_id=plan.id,
        current_user=user,
        payload={
            "action": arguments.get("action"),
            "reason": arguments.get("reason"),
            "human_verified_criteria": arguments.get("human_verified_criteria") or [],
        },
    )
    return {
        "plan_id": result["plan"]["id"],
        "status": result["plan"]["status"],
        "decision": result["decision"]["action"],
    }


async def mcp_work_item_redeclare(
    db: AsyncSession, *, user: User, scope: WorkGrantScope, arguments: dict[str, Any]
) -> dict[str, Any]:
    await require_work_operator(db, user)
    item = await scoped_work_item(db, scope, arguments.get("work_item"))
    return await redeclare_work_item(
        db,
        work_item_id=item.id,
        current_user=user,
        payload={"reason": arguments.get("reason"), "evidence": arguments.get("evidence") or {}},
    )


async def mcp_coding_agent_start(
    db: AsyncSession, *, user: User, scope: WorkGrantScope, arguments: dict[str, Any]
) -> dict[str, Any]:
    await require_work_operator(db, user)
    item = await scoped_work_item(db, scope, arguments.get("work_item"))
    await require_coding_start_targets(db, item, arguments.get("change_unit_ids") or [])
    result = await start_work_item_coding_agent_execution(
        db,
        work_item_id=item.id,
        current_user=user,
        payload={
            "change_unit_ids": arguments.get("change_unit_ids") or [],
            "restart_from_scratch": bool(arguments.get("restart_from_scratch")),
        },
    )
    return {
        "status": result.get("status"),
        "reason": result.get("reason"),
        "session": result.get("session"),
        "blockers": result.get("blockers"),
        "lifecycle_transition": result.get("lifecycle_transition"),
    }


async def mcp_work_item_transition(
    db: AsyncSession, *, user: User, scope: WorkGrantScope, arguments: dict[str, Any]
) -> dict[str, Any]:
    await require_work_operator(db, user)
    item = await scoped_work_item(db, scope, arguments.get("work_item"))
    workflow_id = await transition_workflow_id(db, item, arguments.get("workflow_id"))
    result = await transition_work_item(
        db,
        workflow_id=workflow_id,
        work_item_id=item.id,
        current_user=user,
        payload={"to_state": arguments.get("to_state"), "reason": arguments.get("reason")},
        bind_preview=False,  # binding is for UI previews; this agent path is governed by its MCP work grant
    )
    return {
        "work_state": result["work_state"],
        "jira_sync": result["preview"]["jira_sync_preview"],
    }


async def mcp_coding_observability(
    db: AsyncSession, *, user: User, scope: WorkGrantScope, arguments: dict[str, Any]
) -> dict[str, Any]:
    item = await scoped_work_item(db, scope, arguments.get("work_item"))
    return await get_work_item_coding_observability(db, item.id)


async def mcp_work_item_create(
    db: AsyncSession, *, user: User, scope: WorkGrantScope, arguments: dict[str, Any]
) -> dict[str, Any]:
    requested_project = str(arguments.get("project_id") or "").strip()
    if requested_project:
        # The service re-checks membership; the grant binding narrows it before any write.
        require_listing_project(scope, requested_project)
    item = await create_platform_work_item(
        db,
        current_user=user,
        project_id=str(arguments.get("project_id") or ""),
        title=str(arguments.get("title") or ""),
        description=str(arguments.get("description") or ""),
        issue_type=str(arguments.get("issue_type") or "task"),
        epic_key=str(arguments.get("epic_key") or ""),
        labels=arguments.get("labels") if isinstance(arguments.get("labels"), list) else [],
        priority=str(arguments.get("priority") or "normal"),
    )
    return {
        "id": item.id,
        "source_key": item.source_key,
        "issue_type": item.issue_type,
        "work_state": item.work_state,
        "epic_key": item.epic_key,
        "project_id": item.project_id,
    }


async def mcp_work_item_context(
    db: AsyncSession, *, user: User, scope: WorkGrantScope, arguments: dict[str, Any]
) -> dict[str, Any]:
    # The handover context carries the latest Change Plan: plan navigation read boundary.
    item = await scoped_work_item(db, scope, arguments.get("work_item"))
    return await build_work_item_context(
        db,
        item=item,
        include_session_digests=bool(arguments.get("include_session_digests", True)),
    )


async def mcp_work_item_link_session(
    db: AsyncSession, *, user: User, scope: WorkGrantScope, arguments: dict[str, Any]
) -> dict[str, Any]:
    item = await scoped_work_item(db, scope, arguments.get("work_item"))
    session = await resolve_linkable_session(
        db, item=item, client_session_id=str(arguments.get("client_session_id") or ""), current_user=user
    )
    return await link_validated_session_to_work_item(db, item=item, session=session, current_user=user)


async def mcp_work_item_note(
    db: AsyncSession, *, user: User, scope: WorkGrantScope, arguments: dict[str, Any]
) -> dict[str, Any]:
    item = await scoped_work_item(db, scope, arguments.get("work_item"))
    return await add_work_item_note(db, item=item, note=str(arguments.get("note") or ""), current_user=user)


MCP_SECURE_WORK_TOOL_HANDLERS = {
    "work_item_find": mcp_work_item_find,
    "work_item_list": mcp_work_item_list,
    "work_item_create": mcp_work_item_create,
    "work_item_context": mcp_work_item_context,
    "work_item_link_session": mcp_work_item_link_session,
    "work_item_note": mcp_work_item_note,
    "change_units_plan": mcp_change_units_plan,
    "change_plan_generate": mcp_change_plan_generate,
    "change_plan_decide": mcp_change_plan_decide,
    "work_item_redeclare": mcp_work_item_redeclare,
    "coding_agent_start": mcp_coding_agent_start,
    "work_item_transition": mcp_work_item_transition,
    "coding_observability": mcp_coding_observability,
}


__all__ = ["MCP_SECURE_WORK_TOOL_HANDLERS"]
