"""Handoff attachments: the client's git bundle when the WIP branch cannot be pushed."""

from __future__ import annotations

import hashlib
import uuid
from typing import Any

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import AuditLog, WorkItemHandoffAttachment
from ...time_utils import utc_now
from ..knowledge.identity.workspace import WorkspaceId
from ..knowledge.objects.errors import KnowledgeObjectError
from ..knowledge.objects.source_object import SourceObjectRef
from .bundle_scan import scan_bundle

MAX_ATTACHMENT_BYTES = 50 * 1024 * 1024
PART_BYTES = 16 * 1024 * 1024
STORE_AUDIT_ACTION = "agent_board.handoff_attachment.stored"
READ_AUDIT_ACTION = "agent_board.handoff_attachment.read"
CODE_NOT_CONFIGURED = "attachment_store_not_configured"
CODE_UNAVAILABLE = "attachment_store_unavailable"
CODE_TOO_LARGE = "attachment_too_large"


def attachment_store() -> Any:
    from ..knowledge.runtime import get_evidence_runtime

    return get_evidence_runtime().object_store


def _store() -> Any:
    try:
        return attachment_store()
    except Exception as error:  # noqa: BLE001 - an unconfigured runtime is a typed state, not a 500
        raise HTTPException(status_code=409, detail={"code": CODE_NOT_CONFIGURED}) from error


async def store_bundle(
    db: AsyncSession, *, project_id: str, work_item_id: str, user_id: str, data: bytes
) -> WorkItemHandoffAttachment:
    if not data or len(data) > MAX_ATTACHMENT_BYTES:
        raise HTTPException(status_code=413, detail={"code": CODE_TOO_LARGE})
    refusal = scan_bundle(data)
    if refusal:
        raise HTTPException(status_code=422, detail={"code": refusal})
    store = _store()
    workspace = WorkspaceId.parse(project_id)
    parts = []
    try:
        for start in range(0, len(data), PART_BYTES):
            chunk = data[start:start + PART_BYTES]
            stored = await store.put_if_absent(workspace, chunk)
            ref = stored.ref
            parts.append({"bucket": ref.bucket, "key": ref.key, "version_id": ref.version_id,
                          "content_sha256": ref.content_sha256, "size": len(chunk)})
    except KnowledgeObjectError as error:
        raise HTTPException(status_code=503, detail={"code": CODE_UNAVAILABLE}) from error
    attachment = WorkItemHandoffAttachment(
        id=str(uuid.uuid4()), project_id=project_id, work_item_id=work_item_id, uploaded_by=user_id,
        kind="git_bundle", byte_size=len(data), sha256=hashlib.sha256(data).hexdigest(), parts=parts,
        created_at=utc_now(),
    )
    db.add(attachment)
    db.add(AuditLog(user_id=user_id, action=STORE_AUDIT_ACTION, resource_type="work_item_handoff_attachment",
                    project_id=project_id,
                    resource_id=attachment.id, details={"project_id": project_id, "work_item_id": work_item_id,
                                                        "byte_size": len(data), "sha256": attachment.sha256}))
    await db.flush()
    return attachment


async def load_bundle(db: AsyncSession, *, attachment: WorkItemHandoffAttachment, user_id: str) -> bytes:
    store = _store()
    workspace = WorkspaceId.parse(attachment.project_id)
    try:
        data = b"".join([
            await store.get_verified(workspace, SourceObjectRef(
                bucket=part["bucket"], key=part["key"], version_id=part.get("version_id"),
                content_sha256=part.get("content_sha256")))
            for part in attachment.parts
        ])
    except KnowledgeObjectError as error:
        raise HTTPException(status_code=503, detail={"code": CODE_UNAVAILABLE}) from error
    if hashlib.sha256(data).hexdigest() != attachment.sha256:
        raise HTTPException(status_code=503, detail={"code": CODE_UNAVAILABLE})
    db.add(AuditLog(user_id=user_id, action=READ_AUDIT_ACTION, resource_type="work_item_handoff_attachment",
                    resource_id=attachment.id, project_id=attachment.project_id,
                    details={"project_id": attachment.project_id,
                                                        "work_item_id": attachment.work_item_id}))
    await db.flush()
    return data


__all__ = ["MAX_ATTACHMENT_BYTES", "PART_BYTES", "attachment_store", "load_bundle", "store_bundle"]
