"""A Workspace's structured profile: the instance default or its own versioned document."""

from __future__ import annotations

import json
from collections import OrderedDict
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ....models import AuditLog
from ....models.project.knowledge_structured import KnowledgeStructuredProfile
from ....time_utils import utc_now
from .profile import default_profile_document, parse_profile, structured_profile
from .profile_types import StructuredProfile, StructuredProfileError

AUDIT_ACTION = "knowledge.structured_profile.update"
MAX_DOCUMENT_BYTES = 65_536
MAX_HISTORY = 10
_CACHE_SIZE = 64
_PARSED: OrderedDict[tuple[str, int], StructuredProfile] = OrderedDict()


class StructuredProfileConflictError(Exception):
    pass


def _iso(value) -> str | None:
    return value.isoformat() if value is not None else None


async def _rows(db: AsyncSession, project_id: str, limit: int = 1) -> list[KnowledgeStructuredProfile]:
    return list((await db.execute(
        select(KnowledgeStructuredProfile)
        .where(KnowledgeStructuredProfile.project_id == project_id)
        .order_by(KnowledgeStructuredProfile.revision.desc())
        .limit(limit)
    )).scalars().all())


def validate_document(document: object, *, revision: int = 1) -> StructuredProfile:
    if not isinstance(document, dict):
        raise StructuredProfileError("structured profile: the document must be a JSON object")
    if len(json.dumps(document, ensure_ascii=False).encode("utf-8")) > MAX_DOCUMENT_BYTES:
        raise StructuredProfileError(f"structured profile: the document is larger than {MAX_DOCUMENT_BYTES} bytes")
    return parse_profile(document, workspace_revision=revision)


async def validate_for_workspace(db: AsyncSession, project_id: str, document: object) -> StructuredProfile:
    rows = await _rows(db, project_id)
    return validate_document(document, revision=int(rows[0].revision) + 1 if rows else 1)


async def workspace_profile(db: AsyncSession, project_id: str) -> StructuredProfile:
    rows = await _rows(db, project_id)
    if not rows or rows[0].document is None:
        return structured_profile()
    row = rows[0]
    key = (project_id, int(row.revision))
    cached = _PARSED.get(key)
    if cached is None:
        cached = validate_document(row.document, revision=int(row.revision))
        _PARSED[key] = cached
        while len(_PARSED) > _CACHE_SIZE:
            _PARSED.popitem(last=False)
    _PARSED.move_to_end(key)
    return cached


async def workspace_profile_id(db: AsyncSession, project_id: str) -> str:
    rows = await _rows(db, project_id)
    if rows and rows[0].document is not None and rows[0].profile_id:
        return str(rows[0].profile_id)
    return structured_profile().profile_id


async def save_workspace_profile(
    db: AsyncSession, project_id: str, *, document: dict[str, Any] | None, actor_id: str | None
) -> KnowledgeStructuredProfile:
    # The caller requests the re-extraction, so this module never imports the builds.
    rows = await _rows(db, project_id)
    previous = rows[0] if rows else None
    revision = int(previous.revision) + 1 if previous is not None else 1
    profile = validate_document(document, revision=revision) if document is not None else None
    before = previous.document if previous is not None and previous.document is not None else default_profile_document()
    after = document if document is not None else default_profile_document()
    changed = sorted(key for key in set(before) | set(after) if before.get(key) != after.get(key))
    row = KnowledgeStructuredProfile(
        project_id=project_id, revision=revision, profile_id=profile.profile_id if profile is not None else None,
        document=document, created_by=actor_id, created_at=utc_now(),
    )
    db.add(row)
    if actor_id is not None:
        db.add(AuditLog(
            user_id=actor_id, action=AUDIT_ACTION, resource_type="workspace", resource_id=project_id,
            details={"workspace_id": project_id, "revision": revision, "reset": document is None,
                     "profile_id": row.profile_id or structured_profile().profile_id, "changed_sections": changed},
        ))
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise StructuredProfileConflictError() from None
    return row


async def profile_settings(db: AsyncSession, project_id: str, *, may_author: bool) -> dict[str, Any]:
    rows = await _rows(db, project_id, MAX_HISTORY)
    current = rows[0] if rows and rows[0].document is not None else None
    default = default_profile_document()
    return {
        "workspace_id": project_id,
        "source": "workspace" if current is not None else "default",
        "profile_id": str(current.profile_id) if current is not None else structured_profile().profile_id,
        "revision": int(current.revision) if current is not None else None,
        "document": current.document if current is not None else default,
        "default_document": default,
        "may_author": may_author,
        "history": [
            {"revision": int(row.revision), "profile_id": row.profile_id, "reset": row.document is None,
             "created_by": row.created_by, "created_at": _iso(row.created_at)}
            for row in rows
        ],
    }


__all__ = [
    "AUDIT_ACTION",
    "MAX_DOCUMENT_BYTES",
    "StructuredProfileConflictError",
    "profile_settings",
    "save_workspace_profile",
    "validate_document",
    "validate_for_workspace",
    "workspace_profile",
    "workspace_profile_id",
]
