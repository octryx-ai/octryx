"""A Workspace's structured profile: the instance default or its own versioned document.

The instance default is the profile file (``profiles/structured-v<n>.json``). A Workspace whose
manuals, files or tickets speak another vocabulary (German table headers, other file names, other
ticket numbers) stores its own document of the **same schema**, validated by the same loader the
builds use (``profile.parse_profile``), so a document that saves is a document that builds.

- **Versioned.** Every save is a new row (``knowledge_structured_profiles``) with the next
  revision; the highest revision is in force, a row without a document returns the Workspace to the
  instance default. The Workspace profile id is ``<key>-v<version>-w<revision>``, recorded on every
  node, edge, extraction and build like the default's, so readers see exactly one profile's graph
  and a new revision re-extracts every layer (the route requests that build).
- **Audited.** A save writes ``knowledge.structured_profile.update`` with the revision, the profile
  id, whether it was a reset and the top-level sections that changed; never the document itself.
- **Serialized.** Two saves that read the same latest revision race for the next one; the unique
  ``(project_id, revision)`` key lets exactly one win, the other raises
  :class:`StructuredProfileConflictError` (the route answers 409) with nothing stored or audited,
  so an author never overwrites a revision they have not seen.
- **Bounded.** A document is at most :data:`MAX_DOCUMENT_BYTES`; every pattern passes
  ``profile_patterns.check_pattern`` (the worker runs them on every source of the Workspace).

Readers need only the id (:func:`workspace_profile_id`, no parse); builds parse the document once
per revision (:func:`workspace_profile`, a small per-process cache).
"""

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
    """Another save took the revision this one was computed for; nothing was stored."""


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
    """The profile the document builds as (at ``revision``); :class:`StructuredProfileError` naming the rule."""
    if not isinstance(document, dict):
        raise StructuredProfileError("structured profile: the document must be a JSON object")
    if len(json.dumps(document, ensure_ascii=False).encode("utf-8")) > MAX_DOCUMENT_BYTES:
        raise StructuredProfileError(f"structured profile: the document is larger than {MAX_DOCUMENT_BYTES} bytes")
    return parse_profile(document, workspace_revision=revision)


async def validate_for_workspace(db: AsyncSession, project_id: str, document: object) -> StructuredProfile:
    """The profile the document would build as if saved now (with the Workspace's next revision)."""
    rows = await _rows(db, project_id)
    return validate_document(document, revision=int(rows[0].revision) + 1 if rows else 1)


async def workspace_profile(db: AsyncSession, project_id: str) -> StructuredProfile:
    """The profile a build of this Workspace extracts with."""
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
    """The profile id the Workspace's graph is read under (stored with the revision; nothing is parsed)."""
    rows = await _rows(db, project_id)
    if rows and rows[0].document is not None and rows[0].profile_id:
        return str(rows[0].profile_id)
    return structured_profile().profile_id


async def save_workspace_profile(
    db: AsyncSession, project_id: str, *, document: dict[str, Any] | None, actor_id: str | None
) -> KnowledgeStructuredProfile:
    """Store the next revision (``None``: back to the instance default) and audit it; commits.

    The caller requests the re-extraction (every layer), so this module never imports the builds.
    """
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
    """What the editor shows: the profile in force, the instance default, and the latest revisions."""
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
