"""Durable archive storage for ingested document artifacts."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.services.artifact_store import service as artifact_store


def document_archive_backend() -> str:
    return artifact_store.artifact_store_backend()


def document_archive_object_key(relative_path: str) -> str:
    path = _normalize_relative_path(relative_path)
    prefix = artifact_store.artifact_store_prefix()
    return f"{prefix}/{path}" if prefix else path


def document_archive_filesystem_path(relative_path: str) -> Path:
    return artifact_store.artifact_store_root() / _normalize_relative_path(relative_path)


def write_document_archive_bytes(
    relative_path: str,
    payload: bytes,
    *,
    content_type: str = "application/octet-stream",
    s3_client_factory=None,
    gcs_client_factory=None,
) -> str:
    backend = document_archive_backend()
    normalized = _normalize_relative_path(relative_path)
    if backend == "filesystem":
        target = document_archive_filesystem_path(normalized)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload)
        return normalized
    object_key = document_archive_object_key(normalized)
    if backend == "s3":
        bucket = artifact_store.artifact_store_bucket()
        if not bucket:
            raise RuntimeError("artifact_store_bucket is required when artifact_store_backend=s3")
        client_factory = s3_client_factory or artifact_store._build_s3_client
        client_factory().put_object(Bucket=bucket, Key=object_key, Body=payload, ContentType=content_type)
        return normalized
    if backend == "gcs":
        bucket_name = artifact_store.artifact_store_bucket()
        if not bucket_name:
            raise RuntimeError("artifact_store_bucket is required when artifact_store_backend=gcs")
        client_factory = gcs_client_factory or artifact_store._build_gcs_client
        client_factory().bucket(bucket_name).blob(object_key).upload_from_string(payload, content_type=content_type)
        return normalized
    raise RuntimeError(f"Unsupported artifact store backend: {backend}")


def write_document_archive_file(
    relative_path: str,
    source_path: Path,
    *,
    content_type: str = "application/octet-stream",
) -> str:
    return write_document_archive_bytes(relative_path, source_path.read_bytes(), content_type=content_type)


def archive_document_ingestion_artifacts(
    *,
    bundle_id: str,
    source_id: str,
    artifacts: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    archived: list[dict[str, Any]] = []
    for artifact in artifacts:
        if not isinstance(artifact, dict):
            continue
        path = Path(str(artifact.get("path") or "")).expanduser()
        if not path.exists() or not path.is_file():
            continue
        name = _safe_archive_name(str(artifact.get("name") or path.name))
        relative_path = f"document-ingestion/{_safe_archive_name(bundle_id)}/{_safe_archive_name(source_id)}/{name}"
        archive_path = write_document_archive_file(
            relative_path,
            path,
            content_type=str(artifact.get("media_type") or "application/octet-stream"),
        )
        archived.append(
            {
                "name": name,
                "archive_path": archive_path,
                "object_key": document_archive_object_key(archive_path),
                "storage_backend": document_archive_backend(),
                "media_type": artifact.get("media_type") or "application/octet-stream",
                "size_bytes": artifact.get("size_bytes") or path.stat().st_size,
            }
        )
    return archived


def _safe_archive_name(value: str) -> str:
    cleaned = Path(str(value or "artifact")).name.replace("\\", "/")
    cleaned = "".join(char if char.isalnum() or char in "._-" else "-" for char in cleaned).strip("-.")
    return cleaned or "artifact"


def _normalize_relative_path(value: Any) -> str:
    path = str(value or "").strip().replace("\\", "/").lstrip("/")
    if not path or path == "." or ".." in Path(path).parts:
        raise ValueError(f"Invalid document archive path: {value!r}")
    return Path(path).as_posix()
