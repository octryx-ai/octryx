"""Instructions admin API (``/api/v1/instructions``, A8).

Thin transport over ``services/instructions``: list, detail, create (with its first draft), a new draft
version, the conflict check of a version, submit for four-eyes review (accepting findings explicitly),
publish and retire. Global admins only; refusals are closed codes.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.instructions import review

from ...db import get_db
from ...models import User
from ...services.auth import get_current_user
from ...services.instructions import lifecycle, views
from ...services.worker.admin import require_admin

router = APIRouter(prefix="/api/v1/instructions", tags=["instructions"])


class CreateInstructionRequest(BaseModel):
    key: str = Field(min_length=2, max_length=120)
    title: str = Field(min_length=1, max_length=220)
    scope_type: str = Field(default="global", max_length=16)
    scope_id: str | None = Field(default=None, max_length=36)
    # always | workflow (needs workflow_key) | on_request; empty: workflow when workflow_key is set, else always.
    binding: str | None = Field(default=None, max_length=16)
    workflow_key: str | None = Field(default=None, max_length=180)
    body: str = Field(min_length=1, max_length=12_000)
    change_note: str = Field(default="", max_length=500)


class DraftRequest(BaseModel):
    body: str = Field(min_length=1, max_length=12_000)
    change_note: str = Field(default="", max_length=500)


class SubmitRequest(BaseModel):
    accept_findings: bool = False


class PublishRequest(BaseModel):
    # The single-step publish under the ``single_admin`` approval rule: approve the own pending review first.
    self_approve: bool = False


@contextmanager
def _refusals() -> Iterator[None]:
    try:
        yield
    except lifecycle.InstructionRefusal as refusal:
        raise HTTPException(status_code=refusal.status, detail=refusal.as_detail()) from None


async def _admin(current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> User:
    await require_admin(db, current_user)
    return current_user


async def _detail(db: AsyncSession, instruction_id: str) -> dict[str, Any]:
    detail = await views.instruction_detail(db, instruction_id)
    if detail is None:
        raise HTTPException(status_code=404, detail={"code": "instruction_not_found"})
    return detail


@router.get("")
async def list_instructions(
    include_retired: bool = False, _user: User = Depends(_admin), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    items = await views.list_instructions(db, include_retired=include_retired)
    return {"items": items, "count": len(items)}


@router.get("/{instruction_id}")
async def get_instruction(
    instruction_id: str, _user: User = Depends(_admin), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return await _detail(db, instruction_id)


@router.post("", status_code=201)
async def create_instruction(
    body: CreateInstructionRequest, user: User = Depends(_admin), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    with _refusals():
        instruction, _version = await lifecycle.create_instruction(
            db, key=body.key, title=body.title, scope_type=body.scope_type, scope_id=body.scope_id,
            workflow_key=body.workflow_key, body=body.body, change_note=body.change_note, user=user,
            binding=body.binding,
        )
        await db.commit()
    return await _detail(db, instruction.id)


@router.post("/{instruction_id}/drafts", status_code=201)
async def create_draft(
    instruction_id: str, body: DraftRequest, user: User = Depends(_admin), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    with _refusals():
        version = await lifecycle.create_draft(
            db, instruction_id=instruction_id, body=body.body, change_note=body.change_note, user=user
        )
        await db.commit()
    return views.serialize_version(version)


@router.get("/versions/{version_id}/conflicts")
async def check_version(
    version_id: str, _user: User = Depends(_admin), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    with _refusals():
        findings = await review.check_version(db, version_id=version_id)
    return {"findings": findings}


@router.post("/versions/{version_id}/submit")
async def submit_version(
    version_id: str, body: SubmitRequest, user: User = Depends(_admin), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    with _refusals():
        version = await review.submit_for_review(
            db, version_id=version_id, user=user, accept_findings=body.accept_findings
        )
        await db.commit()
    return views.serialize_version(version)


@router.post("/versions/{version_id}/publish")
async def publish_version(
    version_id: str, body: PublishRequest, user: User = Depends(_admin), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    with _refusals():
        version, gate = await review.publish(db, version_id=version_id, user=user, self_approve=body.self_approve)
        await db.commit()
    return {"version": views.serialize_version(version), "approval_gate": gate}


@router.post("/{instruction_id}/retire")
async def retire_instruction(
    instruction_id: str, user: User = Depends(_admin), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    with _refusals():
        await lifecycle.retire_instruction(db, instruction_id=instruction_id, user=user)
        await db.commit()
    return await _detail(db, instruction_id)
