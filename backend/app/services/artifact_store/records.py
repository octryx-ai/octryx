"""Tool artifact records: persist a payload with its row, load, read and delete them."""

from __future__ import annotations

import gzip
import hashlib
import json
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import ToolArtifact
from .service import (
    _artifact_object_key,
    _artifact_relative_path,
    _compress_payload,
    _delete_artifact_object,
    _read_artifact_object,
    _serialize_payload,
    _write_artifact_object,
    artifact_store_backend,
)


async def persist_tool_artifact_payload(
    db: AsyncSession,
    *,
    artifact_id: str,
    session_id: str,
    message_id: str | None,
    tool_name: str,
    payload: Any,
    preview: dict[str, Any] | None = None,
    serialize_payload_func=_serialize_payload,
    compress_payload_func=_compress_payload,
    artifact_store_backend_func=artifact_store_backend,
    artifact_relative_path_func=_artifact_relative_path,
    artifact_object_key_func=_artifact_object_key,
    write_artifact_object_func=_write_artifact_object,
) -> dict[str, Any]:
    serialized = serialize_payload_func(payload)
    compressed = compress_payload_func(payload)
    sha256 = hashlib.sha256(serialized).hexdigest()
    backend = artifact_store_backend_func()
    location = (
        str(artifact_relative_path_func(session_id=session_id, artifact_id=artifact_id))
        if backend == "filesystem"
        else artifact_object_key_func(session_id=session_id, artifact_id=artifact_id)
    )
    write_artifact_object_func(backend=backend, location=location, payload_bytes=compressed)

    row = ToolArtifact(
        id=str(artifact_id),
        session_id=str(session_id),
        message_id=str(message_id or "") or None,
        tool_name=str(tool_name or "").strip() or "tool",
        storage_backend={
            "filesystem": "disk_json_gzip",
            "s3": "s3_json_gzip",
            "gcs": "gcs_json_gzip",
        }[backend],
        relative_path=location,
        content_sha256=sha256,
        payload_size_bytes=len(serialized),
        is_compressed=True,
        preview_json=preview or {},
    )
    db.add(row)
    await db.flush()
    return {
        "artifact_id": row.id,
        "storage_backend": row.storage_backend,
        "relative_path": row.relative_path,
        "payload_size_bytes": row.payload_size_bytes,
        "content_sha256": row.content_sha256,
        "preview": dict(row.preview_json or {}),
    }


async def load_tool_artifact_record(db: AsyncSession, *, artifact_id: str) -> ToolArtifact | None:
    return (
        await db.execute(select(ToolArtifact).where(ToolArtifact.id == str(artifact_id or "").strip()))
    ).scalar_one_or_none()


def read_tool_artifact_payload(record: ToolArtifact, *, read_artifact_object_func=_read_artifact_object) -> Any:
    storage_backend = str(record.storage_backend or "").strip()
    if storage_backend == "disk_json_gzip":
        backend = "filesystem"
    elif storage_backend == "s3_json_gzip":
        backend = "s3"
    elif storage_backend == "gcs_json_gzip":
        backend = "gcs"
    else:
        raise RuntimeError(f"Unsupported stored artifact backend: {storage_backend}")
    payload_bytes = read_artifact_object_func(backend=backend, location=str(record.relative_path or "").strip())
    return json.loads(gzip.decompress(payload_bytes).decode("utf-8"))


def delete_tool_artifact_file(record: ToolArtifact, *, delete_artifact_object_func=_delete_artifact_object) -> None:
    storage_backend = str(record.storage_backend or "").strip()
    if storage_backend == "disk_json_gzip":
        backend = "filesystem"
    elif storage_backend == "s3_json_gzip":
        backend = "s3"
    elif storage_backend == "gcs_json_gzip":
        backend = "gcs"
    else:
        return
    delete_artifact_object_func(backend=backend, location=str(record.relative_path or "").strip())


async def delete_tool_artifacts_for_sessions(
    db: AsyncSession,
    session_ids: list[str],
    *,
    delete_tool_artifact_file_func=delete_tool_artifact_file,
) -> int:
    normalized = [str(item).strip() for item in session_ids if str(item).strip()]
    if not normalized:
        return 0
    rows = (await db.execute(select(ToolArtifact).where(ToolArtifact.session_id.in_(normalized)))).scalars().all()
    for row in rows:
        delete_tool_artifact_file_func(row)
    result = await db.execute(delete(ToolArtifact).where(ToolArtifact.session_id.in_(normalized)))
    return int(result.rowcount or 0)


async def delete_tool_artifacts_for_tool_call_ids(
    db: AsyncSession,
    tool_call_ids: list[str],
    *,
    delete_tool_artifact_file_func=delete_tool_artifact_file,
) -> int:
    normalized = [str(item).strip() for item in tool_call_ids if str(item).strip()]
    if not normalized:
        return 0
    rows = (await db.execute(select(ToolArtifact).where(ToolArtifact.id.in_(normalized)))).scalars().all()
    for row in rows:
        delete_tool_artifact_file_func(row)
    result = await db.execute(delete(ToolArtifact).where(ToolArtifact.id.in_(normalized)))
    return int(result.rowcount or 0)
