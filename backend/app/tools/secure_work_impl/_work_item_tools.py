"""Platform work-item tools: thin adapters over the platform_items service."""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException

from ...models import User, WorkItem
from ...services.mcp_work_access import (
    WorkGrantScope,
    build_work_grant_scope,
    require_listing_project,
    scoped_work_item,
)
from ..context import ToolContext


async def _require_db_and_user(context: ToolContext) -> tuple[Any, User]:
    if context.db is None:
        raise HTTPException(status_code=500, detail="Database session is required")
    user = await context.db.get(User, context.user_id)
    if user is None:
        raise HTTPException(status_code=403, detail="Unknown user")
    return context.db, user


async def _chat_scope(db: Any, user: User, context: ToolContext) -> WorkGrantScope:
    projects = frozenset(str(project).strip() for project in context.project_ids or () if str(project).strip())
    return await build_work_grant_scope(db, user=user, grant_id=None, binding=projects or None)


async def _item_by_key_or_id(db: Any, user: User, context: ToolContext, value: Any) -> WorkItem:
    return await scoped_work_item(db, await _chat_scope(db, user, context), value)


def _error(exc: HTTPException) -> dict[str, Any]:
    return {"error": str(exc.detail), "status_code": exc.status_code}


async def _open_twin(db, project_id: str, params: dict) -> WorkItem | None:
    from sqlalchemy import select

    from ...services.secure_work.platform_items import PLATFORM_SOURCE_TYPE

    title = str(params.get("title") or "").strip()[:500]
    if not title:
        return None
    issue_type = str(params.get("issue_type") or "task").strip().lower()
    epic = str(params.get("epic_key") or "").strip() or None
    query = select(WorkItem).where(
        WorkItem.project_id == project_id, WorkItem.source_type == PLATFORM_SOURCE_TYPE, WorkItem.title == title,
        WorkItem.issue_type == issue_type, WorkItem.source_status == "open",
        WorkItem.epic_key.is_(None) if epic is None else WorkItem.epic_key == epic,
    ).order_by(WorkItem.created_at).limit(1)
    return (await db.execute(query)).scalar_one_or_none()


class WorkItemCreateTool:
    name = "work_item_create"
    description = "Create a platform-only work item (epic/task), never synced to a tracker."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        from ...services.secure_work.platform_items import create_platform_work_item

        db, user = await _require_db_and_user(context)
        # A project_id that names no Workspace at all is the model's invention (a model sent one and
        # every create failed with "not allowed to access this project"): the chat's own Workspace is meant. A real
        # Workspace outside the chat's scope stays refused below.
        from ...models import Project

        scope_ids = [str(pid) for pid in (context.project_ids or [])]
        named = str(params.get("project_id") or "").strip()
        if named and scope_ids and named not in scope_ids and await db.get(Project, named) is None:
            named = ""
        project_id = named or (scope_ids[0] if scope_ids else "")
        try:
            require_listing_project(await _chat_scope(db, user, context), project_id)
            existing = await _open_twin(db, project_id, params)
            if existing is not None:
                # Gemma re-created T1..T4 in a loop (18 items). The same open item comes back with
                # a plain signal instead of a duplicate.
                return {"id": existing.id, "source_key": existing.source_key, "issue_type": existing.issue_type,
                        "work_state": existing.work_state, "epic_key": existing.epic_key,
                        "project_id": existing.project_id, "already_existed": True,
                        "note": f"{existing.source_key} already exists with this title; do not create it again, "
                                "continue with the next item."}
            item = await create_platform_work_item(
                db,
                current_user=user,
                project_id=project_id,
                title=str(params.get("title") or ""),
                description=str(params.get("description") or ""),
                issue_type=str(params.get("issue_type") or "task"),
                epic_key=str(params.get("epic_key") or ""),
                labels=params.get("labels") if isinstance(params.get("labels"), list) else [],
                priority=str(params.get("priority") or "normal"),
            )
        except HTTPException as exc:
            return _error(exc)
        return {
            "id": item.id,
            "source_key": item.source_key,
            "issue_type": item.issue_type,
            "work_state": item.work_state,
            "epic_key": item.epic_key,
            "project_id": item.project_id,
        }


class WorkItemContextTool:
    name = "work_item_context"
    description = "Full handover context of a work item incl. linked session digests."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        from ...services.secure_work.platform_item_context import build_work_item_context

        db, user = await _require_db_and_user(context)
        try:
            item = await _item_by_key_or_id(db, user, context, params.get("work_item"))
            return await build_work_item_context(
                db,
                item=item,
                include_session_digests=bool(params.get("include_session_digests", True)),
            )
        except HTTPException as exc:
            return _error(exc)


class WorkItemNoteTool:
    name = "work_item_note"
    description = "Append a progress note to a work item for the next worker."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        from ...services.secure_work.platform_items import add_work_item_note

        db, user = await _require_db_and_user(context)
        try:
            item = await _item_by_key_or_id(db, user, context, params.get("work_item"))
            return await add_work_item_note(
                db, item=item, note=str(params.get("note") or ""), current_user=user
            )
        except HTTPException as exc:
            return _error(exc)


class WorkItemLinkSessionTool:
    name = "work_item_link_session"
    description = "Link an ingested external CLI session to a work item."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        from ...services.secure_work.platform_item_sessions import link_session_to_work_item

        db, user = await _require_db_and_user(context)
        try:
            item = await _item_by_key_or_id(db, user, context, params.get("work_item"))
            return await link_session_to_work_item(
                db,
                item=item,
                client_session_id=str(params.get("client_session_id") or ""),
                current_user=user,
            )
        except HTTPException as exc:
            return _error(exc)
