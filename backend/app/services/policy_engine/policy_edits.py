"""Policy-level edits on the set-level draft."""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.content_detection.custom_definitions import DetectorDefinitions

from ...models import PolicySetVersion
from ...models.runtime.governed_revision import (
    REVISION_STATE_DRAFT,
    REVISION_STATE_IN_REVIEW,
    REVISION_STATE_PUBLISHED,
)
from . import store
from .builder import render
from .builder_content import custom_categories
from .builder_model import model_from_json
from .custom_policies import custom_digest
from .engine import cedar_module
from .policy_text import index_statements, join_statements, split_statements

EMPTY_VERSION = 0
ERROR_IF_MATCH_REQUIRED = "policy_set_if_match_required"
ERROR_CONFLICT = "policy_set_draft_conflict"
ERROR_DRAFT_EXISTS = "policy_set_draft_exists"
ERROR_NOT_EDITABLE = "policy_set_version_not_editable"
ERROR_POLICY_NOT_FOUND = "policy_not_found"
ERROR_POLICY_EXISTS = "policy_id_exists"
ERROR_BODY = "policy_edit_body_invalid"
ERROR_BUILDER = "policy_builder_model_invalid"
ERROR_CEDAR = "policy_cedar_statement_invalid"


class PolicyEditError(Exception):
    def __init__(self, code: str, status: int = 409, **details: Any) -> None:
        super().__init__(code)
        self.code = code
        self.status = status
        self.details = details


def _etag(value: str | None) -> str:
    text = str(value or "").strip()
    if text.startswith("W/"):
        text = text[2:]
    return text.strip('"')


async def _open(db: AsyncSession) -> PolicySetVersion | None:
    stmt = (select(PolicySetVersion)
            .where(PolicySetVersion.state.in_([REVISION_STATE_DRAFT, REVISION_STATE_IN_REVIEW]))
            .order_by(PolicySetVersion.version.desc()).limit(1))
    return (await db.execute(stmt)).scalar_one_or_none()


async def open_or_published(db: AsyncSession) -> PolicySetVersion | None:
    return await _open(db) or await store.published(db)


async def _claim(db: AsyncSession, row: PolicySetVersion, expected: str) -> None:
    claimed = await db.execute(
        update(PolicySetVersion)
        .where(PolicySetVersion.id == row.id, PolicySetVersion.state == row.state,
               PolicySetVersion.digest == expected)
        .values(digest=PolicySetVersion.digest)
        .execution_options(synchronize_session=False))
    if claimed.rowcount != 1:
        await db.refresh(row)
        raise PolicyEditError(ERROR_CONFLICT, digest=row.digest)


def _expected(if_match: str | None) -> str:
    expected = _etag(if_match)
    if not expected:
        raise PolicyEditError(ERROR_IF_MATCH_REQUIRED, 428)
    return expected


async def edit_base(
    db: AsyncSession, version: int, if_match: str | None
) -> tuple[PolicySetVersion | None, str, DetectorDefinitions]:
    draft, text, base = await _base_row(db, version, if_match)
    return draft, text, store.detector_definitions(base)


async def _base_row(
    db: AsyncSession, version: int, if_match: str | None
) -> tuple[PolicySetVersion | None, str, PolicySetVersion | None]:
    expected = _expected(if_match)
    if version == EMPTY_VERSION:
        opened = await _open(db)
        if opened is not None or (await db.execute(select(PolicySetVersion.id).limit(1))).first() is not None:
            raise PolicyEditError(ERROR_CONFLICT, current_version=opened.version if opened else None)
        if expected != custom_digest(""):
            raise PolicyEditError(ERROR_CONFLICT, digest=custom_digest(""))
        return None, "", None
    row = await store.get_version(db, version)
    if row.state == REVISION_STATE_DRAFT:
        await _claim(db, row, expected)
        return row, str(row.policies_text or ""), row
    if row.state != REVISION_STATE_PUBLISHED:
        raise PolicyEditError(ERROR_NOT_EDITABLE)
    # Claimed first: a concurrent new draft from the same base is committed (and seen below) before this one runs.
    await _claim(db, row, expected)
    opened = await _open(db)
    if opened is not None:
        raise PolicyEditError(ERROR_DRAFT_EXISTS, version=opened.version, state=opened.state)
    return None, str(row.policies_text or ""), row


def _statement(body: dict[str, Any], detectors: DetectorDefinitions) -> tuple[str, str]:
    if body.get("model") is not None:
        model, issues = model_from_json(body["model"], custom_categories(detectors))
        if model is None:
            raise PolicyEditError(ERROR_BUILDER, 422, issues=issues)
        return model.id, render(model)
    cedar = body["cedar"]
    if not isinstance(cedar, str) or not cedar.strip():
        raise PolicyEditError(ERROR_CEDAR, 422, issues=[{"policy_id": "", "message": "Write one policy."}])
    split = split_statements(cedar)
    try:
        est = json.loads(cedar_module().policies_to_json_str(cedar))
    except ValueError as error:
        raise PolicyEditError(ERROR_CEDAR, 422, issues=[{"policy_id": "", "message": str(error)[:500]}]) from None
    bodies = list((est.get("staticPolicies") or {}).values())
    if len(bodies) != 1 or len(split.statements) != 1 or split.trailer:
        raise PolicyEditError(ERROR_CEDAR, 422, issues=[{"policy_id": "", "message": "Write exactly one policy."}])
    policy_id = str((bodies[0].get("annotations") or {}).get("id") or "")
    if not policy_id:
        raise PolicyEditError(ERROR_CEDAR, 422, issues=[{"policy_id": "", "message": "Add an @id annotation."}])
    return policy_id, split.statements[0]


def _ids(text: str) -> set[str]:
    return {item.policy_id for item in index_statements(text)} if split_statements(text).statements else set()


def _rebuilt(text: str, replace_id: str, new: tuple[str, str] | None) -> str:
    split = split_statements(text)
    statements = [(item.policy_id, item.text) for item in index_statements(text)] if split.statements else []
    if new is None and replace_id not in {policy_id for policy_id, _ in statements}:
        raise PolicyEditError(ERROR_POLICY_NOT_FOUND, 404)
    kept = [(policy_id, statement) for policy_id, statement in statements if policy_id != replace_id]
    if new is not None:
        kept.append(new)
    return join_statements(kept, split.trailer)


async def save_edit(
    db: AsyncSession, draft: PolicySetVersion | None, text: str, note: Any, actor_id: str,
    detectors: DetectorDefinitions,
) -> PolicySetVersion:
    if draft is not None:
        await store.save_draft(db, draft, text=text, note=draft.note if note is None else note, actor_id=actor_id,
                               detectors=detectors)
        return draft
    return await store.create_draft(db, text=text, note=note, actor_id=actor_id, detectors=detectors)


async def put_policy(
    db: AsyncSession, version: int, policy_id: str, body: Any, *, if_match: str | None, actor_id: str
) -> tuple[PolicySetVersion, str]:
    if not isinstance(body, dict) or (body.get("model") is None) == (body.get("cedar") is None):
        raise PolicyEditError(ERROR_BODY, 422)
    draft, text, detectors = await edit_base(db, version, if_match)
    statement = _statement(body, detectors)
    if body.get("create") is True and (policy_id in _ids(text) or statement[0] in _ids(text)):
        raise PolicyEditError(ERROR_POLICY_EXISTS, policy_id=statement[0])
    rebuilt = _rebuilt(text, policy_id, statement)
    return await save_edit(db, draft, rebuilt, body.get("note"), actor_id, detectors), statement[0]


async def delete_policy(
    db: AsyncSession, version: int, policy_id: str, *, if_match: str | None, note: Any, actor_id: str
) -> PolicySetVersion:
    draft, text, detectors = await edit_base(db, version, if_match)
    return await save_edit(db, draft, _rebuilt(text, policy_id, None), note, actor_id, detectors)


async def save_set(
    db: AsyncSession, row: PolicySetVersion, *, text: Any, note: Any, if_match: str | None, actor_id: str
) -> None:
    expected = _expected(if_match)
    if row.state == REVISION_STATE_DRAFT:
        await _claim(db, row, expected)
    await store.save_draft(db, row, text=text, note=note, actor_id=actor_id)


__all__ = [
    "EMPTY_VERSION",
    "ERROR_CONFLICT",
    "ERROR_DRAFT_EXISTS",
    "ERROR_IF_MATCH_REQUIRED",
    "PolicyEditError",
    "delete_policy",
    "edit_base",
    "open_or_published",
    "save_edit",
    "put_policy",
    "save_set",
]
