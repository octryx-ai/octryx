"""Admin routes of the governed policy lists: read, edit (next version) and reset to seed."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ...db import get_db
from ...services.policy_lists import admin as policy_list_admin
from ...services.policy_lists.errors import PolicyListError, as_http_exception
from .._helpers.api_guards import _require_admin_api

router = APIRouter()


class DefaultToolSetEditRequest(BaseModel):
    families: list[Any]
    expected_version: int | None = Field(default=None, ge=1)


class PolicyListEditRequest(BaseModel):
    # A list for the lists; an object for a settings record (``workflow_proposal_settings``).
    values: list[Any] | dict[str, Any]
    expected_version: int | None = Field(default=None, ge=1)


async def _answer(operation) -> JSONResponse:
    try:
        return JSONResponse(await operation)
    except PolicyListError as error:
        raise as_http_exception(error) from None


@router.get("/chat/api/panel/default-tool-sets")
async def panel_list_default_tool_sets(request: Request, db: AsyncSession = Depends(get_db)):
    """The live default tool set per capability class, its seed, catalog drift and history."""
    await _require_admin_api(request, db)
    return JSONResponse(await policy_list_admin.default_tool_sets_payload(db))


@router.put("/chat/api/panel/default-tool-sets/{capability_type}")
async def panel_save_default_tool_set(
    capability_type: str, payload: DefaultToolSetEditRequest, request: Request, db: AsyncSession = Depends(get_db)
):
    admin = await _require_admin_api(request, db)
    return await _answer(
        policy_list_admin.save_default_tool_set(
            db, capability_type, payload.families, actor_id=admin.id, expected_version=payload.expected_version
        )
    )


@router.post("/chat/api/panel/default-tool-sets/{capability_type}/reset")
async def panel_reset_default_tool_set(capability_type: str, request: Request, db: AsyncSession = Depends(get_db)):
    admin = await _require_admin_api(request, db)
    return await _answer(policy_list_admin.reset_default_tool_set(db, capability_type, actor_id=admin.id))


@router.get("/chat/api/panel/policy-lists")
async def panel_list_policy_lists(request: Request, db: AsyncSession = Depends(get_db)):
    await _require_admin_api(request, db)
    return JSONResponse(await policy_list_admin.policy_lists_payload(db))


@router.put("/chat/api/panel/policy-lists/{list_id}")
async def panel_save_policy_list(
    list_id: str, payload: PolicyListEditRequest, request: Request, db: AsyncSession = Depends(get_db)
):
    admin = await _require_admin_api(request, db)
    return await _answer(
        policy_list_admin.save_policy_list(
            db, list_id, payload.values, actor_id=admin.id, expected_version=payload.expected_version
        )
    )


@router.post("/chat/api/panel/policy-lists/{list_id}/reset")
async def panel_reset_policy_list(list_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    admin = await _require_admin_api(request, db)
    return await _answer(policy_list_admin.reset_policy_list(db, list_id, actor_id=admin.id))
