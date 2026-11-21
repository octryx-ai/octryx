"""Session workspace object-storage contract.

The coding runtime still executes against a local filesystem workspace. This
module defines the durable mirror contract used by later sync/restore layers.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Literal

from sqlalchemy.ext.asyncio import AsyncSession

from ...config import get_settings
from ...models import Session
from ..system_config.constants import (
    AGENT_SESSION_WORKSPACE_STORAGE_BACKEND_KEY,
    AGENT_SESSION_WORKSPACE_STORAGE_BUCKET_KEY,
    AGENT_SESSION_WORKSPACE_STORAGE_PREFIX_KEY,
)
from ..system_config.values import get_system_config_value
from .shared import set_session_metadata_value

WorkspaceStorageBackend = Literal["disabled", "filesystem", "s3"]

SESSION_WORKSPACE_STORAGE_METADATA_KEY = "workspace_storage"
SESSION_WORKSPACE_STORAGE_BACKEND_ENV = "OCTRYX_SESSION_WORKSPACE_STORAGE_BACKEND"
SESSION_WORKSPACE_STORAGE_BUCKET_ENV = "OCTRYX_SESSION_WORKSPACE_STORAGE_BUCKET"
SESSION_WORKSPACE_STORAGE_PREFIX_ENV = "OCTRYX_SESSION_WORKSPACE_STORAGE_PREFIX"
DEFAULT_SESSION_WORKSPACE_STORAGE_BACKEND: WorkspaceStorageBackend = "disabled"
SESSION_WORKSPACE_OBJECT_SCOPE = "sessions"
DEFAULT_FILESYSTEM_WORKSPACE_STORAGE_DIRNAME = "session-workspace-objects"
_ALLOWED_BACKENDS: set[str] = {"disabled", "filesystem", "s3"}
_SAFE_OBJECT_SEGMENT_PATTERN = re.compile(r"[^A-Za-z0-9._-]+")


@dataclass(frozen=True)
class SessionWorkspaceStorageConfig:
    backend: WorkspaceStorageBackend = DEFAULT_SESSION_WORKSPACE_STORAGE_BACKEND
    bucket: str = ""
    prefix: str = ""

    @property
    def enabled(self) -> bool:
        return self.backend != "disabled"

    def to_metadata(self) -> dict[str, str]:
        payload = {
            "backend": self.backend,
            "prefix": self.prefix,
            "object_scope": SESSION_WORKSPACE_OBJECT_SCOPE,
        }
        if self.bucket:
            payload["bucket"] = self.bucket
        return payload


@dataclass(frozen=True)
class WorkspaceStorageObject:
    key: str
    size_bytes: int
    etag: str = ""


def normalize_workspace_storage_backend(value: Any) -> WorkspaceStorageBackend:
    backend = str(value or DEFAULT_SESSION_WORKSPACE_STORAGE_BACKEND).strip().lower()
    if backend not in _ALLOWED_BACKENDS:
        return DEFAULT_SESSION_WORKSPACE_STORAGE_BACKEND
    return backend  # type: ignore[return-value]


def normalize_workspace_storage_prefix(value: Any) -> str:
    raw = str(value or "").strip().replace("\\", "/")
    if not raw:
        return ""
    if not raw.strip("/"):
        return ""
    if raw.startswith("/"):
        raise ValueError("Workspace storage prefix must be relative")
    return _normalize_posix_relative_path(raw, allow_empty=True)


def normalize_workspace_object_relative_path(value: Any) -> str:
    return _normalize_posix_relative_path(str(value or "").strip().replace("\\", "/"), allow_empty=False)


def _normalize_posix_relative_path(value: str, *, allow_empty: bool) -> str:
    if not value:
        if allow_empty:
            return ""
        raise ValueError("Workspace object path is required")
    path = PurePosixPath(value)
    if path.is_absolute():
        raise ValueError("Workspace object path must be relative")
    parts = path.parts
    if any(part in {"", ".", ".."} for part in parts):
        raise ValueError("Workspace object path must not contain empty, current, or parent segments")
    return path.as_posix().strip("/")


def safe_workspace_object_segment(value: Any, *, fallback: str = "unknown") -> str:
    cleaned = _SAFE_OBJECT_SEGMENT_PATTERN.sub("-", str(value or "").strip()).strip("-.")
    return cleaned or fallback


def session_workspace_object_prefix(config: SessionWorkspaceStorageConfig, *, session_id: str) -> str:
    session_segment = safe_workspace_object_segment(session_id, fallback="session")
    base = f"{SESSION_WORKSPACE_OBJECT_SCOPE}/{session_segment}"
    return f"{config.prefix}/{base}" if config.prefix else base


def workspace_current_object_key(
    config: SessionWorkspaceStorageConfig,
    *,
    session_id: str,
    relative_path: str,
) -> str:
    path = normalize_workspace_object_relative_path(relative_path)
    return f"{session_workspace_object_prefix(config, session_id=session_id)}/workspace/current/{path}"


def workspace_snapshot_object_key(
    config: SessionWorkspaceStorageConfig,
    *,
    session_id: str,
    revision: str,
    relative_path: str,
) -> str:
    revision_segment = safe_workspace_object_segment(revision, fallback="revision")
    path = normalize_workspace_object_relative_path(relative_path)
    return f"{session_workspace_object_prefix(config, session_id=session_id)}/snapshots/{revision_segment}/{path}"


def workspace_event_object_key(
    config: SessionWorkspaceStorageConfig,
    *,
    session_id: str,
    event_id: str,
) -> str:
    event_segment = safe_workspace_object_segment(event_id, fallback="event")
    return f"{session_workspace_object_prefix(config, session_id=session_id)}/events/{event_segment}.json"


def workspace_manifest_object_key(config: SessionWorkspaceStorageConfig, *, session_id: str) -> str:
    return f"{session_workspace_object_prefix(config, session_id=session_id)}/manifest.json"


def normalize_workspace_storage_object_key(value: Any) -> str:
    return _normalize_posix_relative_path(str(value or "").strip().replace("\\", "/"), allow_empty=False)


def get_session_workspace_storage_metadata(session: Session) -> dict[str, Any] | None:
    metadata = session.metadata_ or {}
    value = metadata.get(SESSION_WORKSPACE_STORAGE_METADATA_KEY)
    return dict(value) if isinstance(value, dict) else None


def set_session_workspace_storage_metadata(session: Session, config: SessionWorkspaceStorageConfig) -> None:
    set_session_metadata_value(session, SESSION_WORKSPACE_STORAGE_METADATA_KEY, config.to_metadata())


async def resolve_session_workspace_storage_config(db: AsyncSession) -> SessionWorkspaceStorageConfig:
    backend_value = await get_system_config_value(db, AGENT_SESSION_WORKSPACE_STORAGE_BACKEND_KEY)
    bucket_value = await get_system_config_value(db, AGENT_SESSION_WORKSPACE_STORAGE_BUCKET_KEY)
    prefix_value = await get_system_config_value(db, AGENT_SESSION_WORKSPACE_STORAGE_PREFIX_KEY)
    backend = normalize_workspace_storage_backend(
        backend_value or os.environ.get(SESSION_WORKSPACE_STORAGE_BACKEND_ENV)
    )
    bucket = str(bucket_value or os.environ.get(SESSION_WORKSPACE_STORAGE_BUCKET_ENV) or "").strip()
    prefix = normalize_workspace_storage_prefix(prefix_value or os.environ.get(SESSION_WORKSPACE_STORAGE_PREFIX_ENV))
    return SessionWorkspaceStorageConfig(backend=backend, bucket=bucket, prefix=prefix)


def _default_filesystem_storage_root() -> Path:
    artifact_dir = Path(get_settings().artifact_store_dir).expanduser().resolve()
    return artifact_dir.parent / DEFAULT_FILESYSTEM_WORKSPACE_STORAGE_DIRNAME


def _filesystem_storage_root(config: SessionWorkspaceStorageConfig) -> Path:
    configured = str(config.bucket or "").strip()
    root = Path(configured).expanduser().resolve() if configured else _default_filesystem_storage_root().resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


def _filesystem_object_path(config: SessionWorkspaceStorageConfig, object_key: str) -> Path:
    root = _filesystem_storage_root(config)
    normalized_key = normalize_workspace_storage_object_key(object_key)
    target = (root / normalized_key).resolve()
    if root not in target.parents and target != root:
        raise ValueError("Workspace storage object path must stay inside the filesystem storage root")
    return target


def _build_s3_client() -> Any:
    import boto3

    settings = get_settings()
    kwargs: dict[str, Any] = {}
    if settings.artifact_store_s3_region:
        kwargs["region_name"] = settings.artifact_store_s3_region
    if settings.artifact_store_s3_endpoint_url:
        kwargs["endpoint_url"] = settings.artifact_store_s3_endpoint_url
    return boto3.client("s3", **kwargs)


def _require_enabled_backend(config: SessionWorkspaceStorageConfig) -> WorkspaceStorageBackend:
    if config.backend == "disabled":
        raise RuntimeError("Session workspace object storage is disabled")
    return config.backend


def _require_s3_bucket(config: SessionWorkspaceStorageConfig) -> str:
    bucket = str(config.bucket or "").strip()
    if not bucket:
        raise RuntimeError("workspace storage bucket is required when backend=s3")
    return bucket


def put_workspace_storage_object(
    config: SessionWorkspaceStorageConfig,
    *,
    object_key: str,
    payload: bytes,
    content_type: str = "application/octet-stream",
    s3_client_factory=_build_s3_client,
) -> WorkspaceStorageObject:
    key = normalize_workspace_storage_object_key(object_key)
    body = bytes(payload or b"")
    backend = _require_enabled_backend(config)
    if backend == "filesystem":
        target = _filesystem_object_path(config, key)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(body)
        return WorkspaceStorageObject(key=key, size_bytes=len(body))
    if backend == "s3":
        bucket = _require_s3_bucket(config)  # before the client: building it resolves AWS credentials
        client = s3_client_factory()
        client.put_object(Bucket=bucket, Key=key, Body=body, ContentType=content_type)
        return WorkspaceStorageObject(key=key, size_bytes=len(body))
    raise RuntimeError(f"Unsupported workspace storage backend: {backend}")


def get_workspace_storage_object(
    config: SessionWorkspaceStorageConfig,
    *,
    object_key: str,
    s3_client_factory=_build_s3_client,
) -> bytes:
    key = normalize_workspace_storage_object_key(object_key)
    backend = _require_enabled_backend(config)
    if backend == "filesystem":
        return _filesystem_object_path(config, key).read_bytes()
    if backend == "s3":
        bucket = _require_s3_bucket(config)  # before the client: building it resolves AWS credentials
        client = s3_client_factory()
        response = client.get_object(Bucket=bucket, Key=key)
        return response["Body"].read()
    raise RuntimeError(f"Unsupported workspace storage backend: {backend}")


def delete_workspace_storage_object(
    config: SessionWorkspaceStorageConfig,
    *,
    object_key: str,
    s3_client_factory=_build_s3_client,
) -> None:
    key = normalize_workspace_storage_object_key(object_key)
    backend = _require_enabled_backend(config)
    if backend == "filesystem":
        _filesystem_object_path(config, key).unlink(missing_ok=True)
        return
    if backend == "s3":
        bucket = _require_s3_bucket(config)  # before the client: building it resolves AWS credentials
        client = s3_client_factory()
        client.delete_object(Bucket=bucket, Key=key)
        return
    raise RuntimeError(f"Unsupported workspace storage backend: {backend}")


def list_workspace_storage_objects(
    config: SessionWorkspaceStorageConfig,
    *,
    object_prefix: str,
    s3_client_factory=_build_s3_client,
) -> list[WorkspaceStorageObject]:
    prefix = normalize_workspace_storage_prefix(object_prefix)
    backend = _require_enabled_backend(config)
    if backend == "filesystem":
        root = _filesystem_storage_root(config)
        base = _filesystem_object_path(config, prefix) if prefix else root
        if not base.exists():
            return []
        files = [base] if base.is_file() else [item for item in base.rglob("*") if item.is_file()]
        return [
            WorkspaceStorageObject(
                key=item.relative_to(root).as_posix(),
                size_bytes=item.stat().st_size,
            )
            for item in sorted(files, key=lambda path: path.as_posix())
        ]
    if backend == "s3":
        bucket = _require_s3_bucket(config)  # before the client: building it resolves AWS credentials
        client = s3_client_factory()
        response = client.list_objects_v2(Bucket=bucket, Prefix=prefix)
        return [
            WorkspaceStorageObject(
                key=str(item.get("Key") or ""),
                size_bytes=int(item.get("Size") or 0),
                etag=str(item.get("ETag") or "").strip('"'),
            )
            for item in response.get("Contents", [])
            if item.get("Key")
        ]
    raise RuntimeError(f"Unsupported workspace storage backend: {backend}")


def put_workspace_manifest(
    config: SessionWorkspaceStorageConfig,
    *,
    session_id: str,
    manifest: dict[str, Any],
    s3_client_factory=_build_s3_client,
) -> WorkspaceStorageObject:
    payload = json.dumps(manifest, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    return put_workspace_storage_object(
        config,
        object_key=workspace_manifest_object_key(config, session_id=session_id),
        payload=payload,
        content_type="application/json",
        s3_client_factory=s3_client_factory,
    )


def get_workspace_manifest(
    config: SessionWorkspaceStorageConfig,
    *,
    session_id: str,
    s3_client_factory=_build_s3_client,
) -> dict[str, Any]:
    payload = get_workspace_storage_object(
        config,
        object_key=workspace_manifest_object_key(config, session_id=session_id),
        s3_client_factory=s3_client_factory,
    )
    value = json.loads(payload.decode("utf-8"))
    return value if isinstance(value, dict) else {}


__all__ = [
    "DEFAULT_SESSION_WORKSPACE_STORAGE_BACKEND",
    "SESSION_WORKSPACE_OBJECT_SCOPE",
    "SESSION_WORKSPACE_STORAGE_BACKEND_ENV",
    "SESSION_WORKSPACE_STORAGE_BUCKET_ENV",
    "SESSION_WORKSPACE_STORAGE_METADATA_KEY",
    "SESSION_WORKSPACE_STORAGE_PREFIX_ENV",
    "DEFAULT_FILESYSTEM_WORKSPACE_STORAGE_DIRNAME",
    "SessionWorkspaceStorageConfig",
    "WorkspaceStorageBackend",
    "WorkspaceStorageObject",
    "delete_workspace_storage_object",
    "get_workspace_manifest",
    "get_workspace_storage_object",
    "get_session_workspace_storage_metadata",
    "list_workspace_storage_objects",
    "normalize_workspace_object_relative_path",
    "normalize_workspace_storage_backend",
    "normalize_workspace_storage_object_key",
    "normalize_workspace_storage_prefix",
    "put_workspace_manifest",
    "put_workspace_storage_object",
    "resolve_session_workspace_storage_config",
    "safe_workspace_object_segment",
    "session_workspace_object_prefix",
    "set_session_workspace_storage_metadata",
    "workspace_current_object_key",
    "workspace_event_object_key",
    "workspace_manifest_object_key",
    "workspace_snapshot_object_key",
]
