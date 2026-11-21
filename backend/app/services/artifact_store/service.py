"""Pluggable object store for large tool artifacts."""

from __future__ import annotations

import gzip
import json
from pathlib import Path
from typing import Any

from ...config import get_settings

settings = get_settings()

INLINE_RESULT_MAX_BYTES = 12_000
ALLOWED_ARTIFACT_STORE_BACKENDS = {"filesystem", "s3", "gcs"}


def _normalize_backend(value: Any) -> str:
    backend = str(value or "filesystem").strip().lower()
    return backend if backend in ALLOWED_ARTIFACT_STORE_BACKENDS else "filesystem"


def artifact_store_backend() -> str:
    return _normalize_backend(settings.artifact_store_backend)


def artifact_store_bucket() -> str:
    return str(settings.artifact_store_bucket or "").strip()


def artifact_store_prefix() -> str:
    return str(settings.artifact_store_prefix or "").strip().strip("/")


def artifact_store_root() -> Path:
    root = Path(settings.artifact_store_dir).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


def _artifact_relative_path(*, session_id: str, artifact_id: str) -> Path:
    safe_session = str(session_id or "unknown").strip() or "unknown"
    safe_artifact = str(artifact_id or "").strip()
    return Path("tool-artifacts") / safe_session / f"{safe_artifact}.json.gz"


def _artifact_object_key(*, session_id: str, artifact_id: str) -> str:
    relative = _artifact_relative_path(session_id=session_id, artifact_id=artifact_id).as_posix()
    prefix = artifact_store_prefix()
    return f"{prefix}/{relative}" if prefix else relative


def _serialize_payload(payload: Any) -> bytes:
    return json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")


def _compress_payload(payload: Any) -> bytes:
    return gzip.compress(_serialize_payload(payload))


def should_externalize_payload(payload: Any) -> bool:
    return len(_serialize_payload(payload)) > INLINE_RESULT_MAX_BYTES


def build_tool_result_storage_pointer(
    *,
    artifact_id: str,
    payload_size_bytes: int,
    content_sha256: str,
    preview: dict[str, Any],
) -> dict[str, Any]:
    return {
        "_artifact_storage": "external_json_gzip",
        "artifact_id": str(artifact_id or "").strip(),
        "payload_size_bytes": int(payload_size_bytes or 0),
        "content_sha256": str(content_sha256 or "").strip(),
        "preview": preview,
    }


def _build_s3_client() -> Any:
    import boto3

    kwargs: dict[str, Any] = {}
    if settings.artifact_store_s3_region:
        kwargs["region_name"] = settings.artifact_store_s3_region
    if settings.artifact_store_s3_endpoint_url:
        kwargs["endpoint_url"] = settings.artifact_store_s3_endpoint_url
    return boto3.client("s3", **kwargs)


def _build_gcs_client() -> Any:
    from google.cloud import storage

    return storage.Client()


def _write_filesystem_object(relative_path: str, payload_bytes: bytes) -> None:
    absolute_path = artifact_store_root() / relative_path
    absolute_path.parent.mkdir(parents=True, exist_ok=True)
    absolute_path.write_bytes(payload_bytes)


def _read_filesystem_object(relative_path: str) -> bytes:
    absolute_path = artifact_store_root() / relative_path
    return absolute_path.read_bytes()


def _delete_filesystem_object(relative_path: str) -> None:
    absolute_path = artifact_store_root() / relative_path
    try:
        absolute_path.unlink(missing_ok=True)
    except OSError:
        pass


def _write_s3_object(object_key: str, payload_bytes: bytes) -> None:
    bucket = artifact_store_bucket()
    if not bucket:
        raise RuntimeError("artifact_store_bucket is required when artifact_store_backend=s3")
    client = _build_s3_client()
    client.put_object(Bucket=bucket, Key=object_key, Body=payload_bytes, ContentType="application/gzip")


def _read_s3_object(object_key: str) -> bytes:
    bucket = artifact_store_bucket()
    if not bucket:
        raise RuntimeError("artifact_store_bucket is required when artifact_store_backend=s3")
    client = _build_s3_client()
    response = client.get_object(Bucket=bucket, Key=object_key)
    return response["Body"].read()


def _delete_s3_object(object_key: str) -> None:
    bucket = artifact_store_bucket()
    if not bucket:
        return
    client = _build_s3_client()
    client.delete_object(Bucket=bucket, Key=object_key)


def _write_gcs_object(object_key: str, payload_bytes: bytes) -> None:
    bucket_name = artifact_store_bucket()
    if not bucket_name:
        raise RuntimeError("artifact_store_bucket is required when artifact_store_backend=gcs")
    client = _build_gcs_client()
    bucket = client.bucket(bucket_name)
    blob = bucket.blob(object_key)
    blob.upload_from_string(payload_bytes, content_type="application/gzip")


def _read_gcs_object(object_key: str) -> bytes:
    bucket_name = artifact_store_bucket()
    if not bucket_name:
        raise RuntimeError("artifact_store_bucket is required when artifact_store_backend=gcs")
    client = _build_gcs_client()
    bucket = client.bucket(bucket_name)
    blob = bucket.blob(object_key)
    return blob.download_as_bytes()


def _delete_gcs_object(object_key: str) -> None:
    bucket_name = artifact_store_bucket()
    if not bucket_name:
        return
    client = _build_gcs_client()
    bucket = client.bucket(bucket_name)
    blob = bucket.blob(object_key)
    blob.delete()


def _write_artifact_object(*, backend: str, location: str, payload_bytes: bytes) -> None:
    if backend == "filesystem":
        _write_filesystem_object(location, payload_bytes)
        return
    if backend == "s3":
        _write_s3_object(location, payload_bytes)
        return
    if backend == "gcs":
        _write_gcs_object(location, payload_bytes)
        return
    raise RuntimeError(f"Unsupported artifact store backend: {backend}")


def _read_artifact_object(*, backend: str, location: str) -> bytes:
    if backend == "filesystem":
        return _read_filesystem_object(location)
    if backend == "s3":
        return _read_s3_object(location)
    if backend == "gcs":
        return _read_gcs_object(location)
    raise RuntimeError(f"Unsupported artifact store backend: {backend}")


def _delete_artifact_object(*, backend: str, location: str) -> None:
    if backend == "filesystem":
        _delete_filesystem_object(location)
        return
    if backend == "s3":
        _delete_s3_object(location)
        return
    if backend == "gcs":
        _delete_gcs_object(location)
        return


# The record functions live in ``records``, which imports the storage helpers above; this import
# comes last so they are defined when ``records`` loads, and they are importable from here too.

__all__ = [
    "ALLOWED_ARTIFACT_STORE_BACKENDS",
    "INLINE_RESULT_MAX_BYTES",
    "artifact_store_backend",
    "artifact_store_bucket",
    "artifact_store_prefix",
    "artifact_store_root",
    "build_tool_result_storage_pointer",
    "should_externalize_payload",
]
