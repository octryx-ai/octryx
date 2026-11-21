"""The Confluence page picker: one level of a space's page tree, read-only.

``GET /chat/api/panel/connectors/confluence/page-tree?space_key=&parent_id=&start=&limit=`` (global) and
``GET /chat/api/panel/projects/{project_id}/connectors/confluence/page-tree?...`` (a Workspace): the top-level
pages of an allowed space, or the child pages of one page, read with the saved connection that serves the
space in that scope (``services/confluence_pages``). Admin only; nothing is stored.
"""

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.services.confluence_pages.tree import read_level, tree_request
from app.services.confluence_pages.tree_connection import global_space_config, workspace_space_config
from app.web._helpers.api_guards import _require_admin_api

router = APIRouter()


@router.get("/chat/api/panel/connectors/confluence/page-tree")
async def panel_confluence_page_tree(
    request: Request,
    space_key: str = "",
    parent_id: str = "",
    start: int = 0,
    limit: int = 25,
    db: AsyncSession = Depends(get_db),
):
    await _require_admin_api(request, db)
    space, parent, begin, size = tree_request(space_key, parent_id, start, limit)
    config = await global_space_config(db, space)
    return JSONResponse(await read_level(config, space_key=space, parent_id=parent, start=begin, limit=size))


@router.get("/chat/api/panel/projects/{project_id}/connectors/confluence/page-tree")
async def panel_workspace_confluence_page_tree(
    request: Request,
    project_id: str,
    space_key: str = "",
    parent_id: str = "",
    start: int = 0,
    limit: int = 25,
    db: AsyncSession = Depends(get_db),
):
    await _require_admin_api(request, db)
    space, parent, begin, size = tree_request(space_key, parent_id, start, limit)
    config = await workspace_space_config(db, project_id, space)
    return JSONResponse(await read_level(config, space_key=space, parent_id=parent, start=begin, limit=size))
