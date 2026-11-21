"""Durable archive storage for Engineering Knowledge source artifacts."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..artifact_store import service as artifact_store
from .archive_paths import default_engineering_knowledge_archive_base_path


def engineering_archive_backend() -> str:
    return artifact_store.artifact_store_backend()


def engineering_archive_object_key(relative_path: str) -> str:
    path = _normalize_relative_path(relative_path)
    prefix = artifact_store.artifact_store_prefix()
    return f"{prefix}/{path}" if prefix else path


def engineering_archive_filesystem_path(relative_path: str, *, archive_base_path: Path | None = None) -> Path:
    base_path = (
        archive_base_path.expanduser().resolve()
        if archive_base_path
        else default_engineering_knowledge_archive_base_path()
    )
    return base_path / _normalize_relative_path(relative_path)


def write_engineering_archive_bytes(
    relative_path: str,
    payload: bytes,
    *,
    content_type: str = "application/octet-stream",
    s3_client_factory=None,
    gcs_client_factory=None,
) -> str:
    backend = engineering_archive_backend()
    normalized = _normalize_relative_path(relative_path)
    if backend == "filesystem":
        target = engineering_archive_filesystem_path(normalized)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload)
        return normalized
    object_key = engineering_archive_object_key(normalized)
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
        client_factory().bucket(bucket_name).blob(object_key).upload_from_string(
            payload,
            content_type=content_type,
        )
        return normalized
    raise RuntimeError(f"Unsupported artifact store backend: {backend}")


def write_engineering_archive_text(relative_path: str, content: str, *, content_type: str = "text/plain") -> str:
    return write_engineering_archive_bytes(relative_path, content.encode("utf-8"), content_type=content_type)


def read_engineering_archive_bytes(
    relative_path: str,
    *,
    archive_base_path: Path | None = None,
    s3_client_factory=None,
    gcs_client_factory=None,
) -> bytes:
    backend = engineering_archive_backend()
    normalized = _normalize_relative_path(relative_path)
    if backend == "filesystem":
        return engineering_archive_filesystem_path(normalized, archive_base_path=archive_base_path).read_bytes()
    object_key = engineering_archive_object_key(normalized)
    if backend == "s3":
        bucket = artifact_store.artifact_store_bucket()
        if not bucket:
            raise RuntimeError("artifact_store_bucket is required when artifact_store_backend=s3")
        client_factory = s3_client_factory or artifact_store._build_s3_client
        return client_factory().get_object(Bucket=bucket, Key=object_key)["Body"].read()
    if backend == "gcs":
        bucket_name = artifact_store.artifact_store_bucket()
        if not bucket_name:
            raise RuntimeError("artifact_store_bucket is required when artifact_store_backend=gcs")
        client_factory = gcs_client_factory or artifact_store._build_gcs_client
        return client_factory().bucket(bucket_name).blob(object_key).download_as_bytes()
    raise RuntimeError(f"Unsupported artifact store backend: {backend}")


def read_engineering_archive_text(relative_path: str, *, archive_base_path: Path | None = None) -> str:
    return read_engineering_archive_bytes(relative_path, archive_base_path=archive_base_path).decode(
        "utf-8",
        errors="replace",
    )


def engineering_archive_exists(
    relative_path: str,
    *,
    archive_base_path: Path | None = None,
    s3_client_factory=None,
    gcs_client_factory=None,
) -> bool:
    backend = engineering_archive_backend()
    normalized = _normalize_relative_path(relative_path)
    if backend == "filesystem":
        return engineering_archive_filesystem_path(normalized, archive_base_path=archive_base_path).is_file()
    try:
        if backend == "s3":
            bucket = artifact_store.artifact_store_bucket()
            if not bucket:
                return False
            client_factory = s3_client_factory or artifact_store._build_s3_client
            client_factory().head_object(Bucket=bucket, Key=engineering_archive_object_key(normalized))
            return True
        if backend == "gcs":
            bucket_name = artifact_store.artifact_store_bucket()
            if not bucket_name:
                return False
            client_factory = gcs_client_factory or artifact_store._build_gcs_client
            blob = client_factory().bucket(bucket_name).blob(engineering_archive_object_key(normalized))
            return bool(blob.exists())
    except Exception:
        return False
    return False


def _normalize_relative_path(value: Any) -> str:
    path = str(value or "").strip().replace("\\", "/").lstrip("/")
    if not path or path == "." or ".." in Path(path).parts:
        raise ValueError(f"Invalid Engineering Knowledge archive path: {value!r}")
    return Path(path).as_posix()
