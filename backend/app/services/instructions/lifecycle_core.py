"""Shared pieces of the instruction lifecycle: the refusal, audit rows, checks, versions and loading."""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import AgentDefinition, AuditLog, Project
from ...models.runtime.instruction import (
    INSTRUCTION_SCOPE_AGENT,
    INSTRUCTION_SCOPE_GLOBAL,
    INSTRUCTION_SCOPE_WORKSPACE,
    INSTRUCTION_SCOPES,
    Instruction,
    InstructionVersion,
)
from ...time_utils import utc_now
from .contract import MAX_BODY_CHARS, body_digest, token_estimate


class InstructionRefusal(Exception):  # noqa: N818 - a closed refusal, not an error condition
    def __init__(self, code: str, status: int = 409, **facts: object) -> None:
        super().__init__(code)
        self.code = code
        self.status = status
        self.facts = facts

    def as_detail(self) -> dict[str, object]:
        return {"code": self.code, **self.facts}


def _audit(db: AsyncSession, *, user_id: str, action: str, instruction: Instruction, details: dict[str, Any]) -> None:
    workspace = instruction.scope_id if instruction.scope_type == INSTRUCTION_SCOPE_WORKSPACE else None
    db.add(AuditLog(user_id=user_id, action=action, resource_type="instruction", resource_id=instruction.id,
                    project_id=workspace, details=details))


def _facts(version: InstructionVersion) -> dict[str, Any]:
    return {"version": version.version, "digest": version.digest, "state": version.state}


def _checked_body(body: str) -> str:
    text = str(body or "").strip()
    if not text:
        raise InstructionRefusal("instruction_body_empty", 422)
    if len(text) > MAX_BODY_CHARS:
        raise InstructionRefusal("instruction_body_too_long", 422, max_chars=MAX_BODY_CHARS)
    return text


async def _checked_scope(db: AsyncSession, scope_type: str, scope_id: str | None) -> tuple[str, str | None]:
    kind = str(scope_type or INSTRUCTION_SCOPE_GLOBAL).strip()
    ident = str(scope_id or "").strip() or None
    if kind not in INSTRUCTION_SCOPES or (kind == INSTRUCTION_SCOPE_GLOBAL) != (ident is None):
        raise InstructionRefusal("instruction_scope_invalid", 422)
    if kind == INSTRUCTION_SCOPE_WORKSPACE and await db.get(Project, ident) is None:
        raise InstructionRefusal("instruction_scope_not_found", 404)
    if kind == INSTRUCTION_SCOPE_AGENT and await db.get(AgentDefinition, ident) is None:
        raise InstructionRefusal("instruction_scope_not_found", 404)
    return kind, ident


async def _add_version(
    db: AsyncSession, instruction: Instruction, *, body: str, user_id: str, change_note: str, source: str = "admin",
    state: str = "draft",
) -> InstructionVersion:
    number = (
        await db.execute(
            select(func.coalesce(func.max(InstructionVersion.version), 0)).where(
                InstructionVersion.instruction_id == instruction.id
            )
        )
    ).scalar_one()
    now = utc_now()
    version = InstructionVersion(
        instruction_id=instruction.id, version=int(number) + 1, body=body, digest=body_digest(body),
        token_estimate=token_estimate(body), state=state, source=source, change_note=str(change_note or "")[:500],
        findings_json=[], findings_accepted=0, created_by=user_id, created_at=now,
        published_by=user_id if state == "published" else None, published_at=now if state == "published" else None,
    )
    db.add(version)
    instruction.updated_at = now
    await db.flush()
    return version


async def load_instruction(db: AsyncSession, instruction_id: str) -> Instruction:
    instruction = await db.get(Instruction, instruction_id)
    if instruction is None:
        raise InstructionRefusal("instruction_not_found", 404)
    return instruction


async def load_version(db: AsyncSession, version_id: str) -> tuple[Instruction, InstructionVersion]:
    version = await db.get(InstructionVersion, version_id)
    if version is None:
        raise InstructionRefusal("instruction_version_not_found", 404)
    return await load_instruction(db, version.instruction_id), version
