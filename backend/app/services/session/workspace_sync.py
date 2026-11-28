"""Session workspace sync helpers. The local workspace stays authoritative for execution; these mirror selected changes
into durable storage."""

from __future__ import annotations

import fnmatch
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ...models import Session
from ...time_utils import utc_now_aware
from ..error_facts import error_text
from ..system_config.constants import (
    AGENT_SESSION_WORKSPACE_SYNC_EXCLUDED_DIRS_KEY,
    AGENT_SESSION_WORKSPACE_SYNC_EXCLUDED_GLOBS_KEY,
    AGENT_SESSION_WORKSPACE_SYNC_MAX_FILE_COUNT_KEY,
    AGENT_SESSION_WORKSPACE_SYNC_MAX_FILE_SIZE_BYTES_KEY,
)
from ..system_config.values import get_system_config_value, set_system_config_value
from .shared import get_session_metadata
from .workspace_storage import (
    SESSION_WORKSPACE_STORAGE_METADATA_KEY,
    delete_workspace_storage_object,
    put_workspace_manifest,
    put_workspace_storage_object,
    resolve_session_workspace_storage_config,
    set_session_workspace_storage_metadata,
    workspace_current_object_key,
)

DEFAULT_SYNC_EXCLUDED_DIRS = frozenset(
    {
        ".git",
        ".mypy_cache",
        ".next",
        ".pytest_cache",
        ".ruff_cache",
        ".venv",
        "__pycache__",
        "build",
        "dist",
        "node_modules",
        "target",
        "venv",
    }
)
DEFAULT_SYNC_EXCLUDED_GLOBS = frozenset({".DS_Store", "*.pyc"})
DEFAULT_SYNC_MAX_FILE_COUNT = 5000


@dataclass(frozen=True)
class WorkspaceSyncPolicy:
    excluded_dirs: frozenset[str] = DEFAULT_SYNC_EXCLUDED_DIRS
    excluded_globs: frozenset[str] = DEFAULT_SYNC_EXCLUDED_GLOBS
    max_file_size_bytes: int = 0
    max_file_count: int = DEFAULT_SYNC_MAX_FILE_COUNT


def _parse_csv_set(value: Any) -> frozenset[str]:
    if isinstance(value, (list, tuple, set)):
        return frozenset(str(item).strip() for item in value if str(item).strip())
    return frozenset(item.strip() for item in str(value or "").split(",") if item.strip())


def _bounded_positive_int(value: Any, *, default: int, maximum: int) -> int:
    try:
        parsed = int(str(value or "").strip())
    except (TypeError, ValueError):
        return default
    return max(0, min(parsed, maximum))


async def resolve_workspace_sync_policy(db: AsyncSession | None) -> WorkspaceSyncPolicy:
    if db is None:
        return WorkspaceSyncPolicy()
    excluded_dirs = _parse_csv_set(await get_system_config_value(db, AGENT_SESSION_WORKSPACE_SYNC_EXCLUDED_DIRS_KEY))
    excluded_globs = _parse_csv_set(await get_system_config_value(db, AGENT_SESSION_WORKSPACE_SYNC_EXCLUDED_GLOBS_KEY))
    max_file_size = _bounded_positive_int(
        await get_system_config_value(db, AGENT_SESSION_WORKSPACE_SYNC_MAX_FILE_SIZE_BYTES_KEY),
        default=0,
        maximum=1024 * 1024 * 1024,
    )
    max_file_count = _bounded_positive_int(
        await get_system_config_value(db, AGENT_SESSION_WORKSPACE_SYNC_MAX_FILE_COUNT_KEY),
        default=DEFAULT_SYNC_MAX_FILE_COUNT,
        maximum=100000,
    )
    return WorkspaceSyncPolicy(
        excluded_dirs=DEFAULT_SYNC_EXCLUDED_DIRS | excluded_dirs,
        excluded_globs=DEFAULT_SYNC_EXCLUDED_GLOBS | excluded_globs,
        max_file_size_bytes=max_file_size,
        max_file_count=max_file_count or DEFAULT_SYNC_MAX_FILE_COUNT,
    )


async def save_workspace_sync_policy_settings(
    db: AsyncSession,
    *,
    excluded_dirs: str | None = None,
    excluded_globs: str | None = None,
    max_file_size_bytes: int | None = None,
    max_file_count: int | None = None,
) -> None:
    if excluded_dirs is not None:
        await set_system_config_value(
            db,
            key=AGENT_SESSION_WORKSPACE_SYNC_EXCLUDED_DIRS_KEY,
            value=", ".join(sorted(_parse_csv_set(excluded_dirs))) or None,
            description="Additional directory names excluded from session workspace object-storage sync.",
        )
    if excluded_globs is not None:
        await set_system_config_value(
            db,
            key=AGENT_SESSION_WORKSPACE_SYNC_EXCLUDED_GLOBS_KEY,
            value=", ".join(sorted(_parse_csv_set(excluded_globs))) or None,
            description="Additional file glob patterns excluded from session workspace object-storage sync.",
        )
    if max_file_size_bytes is not None:
        await set_system_config_value(
            db,
            key=AGENT_SESSION_WORKSPACE_SYNC_MAX_FILE_SIZE_BYTES_KEY,
            value=str(_bounded_positive_int(max_file_size_bytes, default=0, maximum=1024 * 1024 * 1024)) or None,
            description=(
                "Maximum single file size in bytes for automatic session workspace sync. Zero disables the cap."
            ),
        )
    if max_file_count is not None:
        await set_system_config_value(
            db,
            key=AGENT_SESSION_WORKSPACE_SYNC_MAX_FILE_COUNT_KEY,
            value=str(_bounded_positive_int(max_file_count, default=DEFAULT_SYNC_MAX_FILE_COUNT, maximum=100000)),
            description="Maximum file count scanned during session workspace snapshot/full sync.",
        )


def _path_within_root(root: Path, candidate: Path) -> bool:
    resolved_root = root.resolve()
    resolved_candidate = candidate.resolve()
    return resolved_candidate == resolved_root or resolved_root in resolved_candidate.parents


def _should_skip_workspace_file(root: Path, path: Path, *, policy: WorkspaceSyncPolicy | None = None) -> bool:
    sync_policy = policy or WorkspaceSyncPolicy()
    try:
        relative = path.relative_to(root)
    except ValueError:
        return True
    relative_text = relative.as_posix()
    if any(part in sync_policy.excluded_dirs for part in relative.parts):
        return True
    if any(
        fnmatch.fnmatch(relative_text, pattern) or fnmatch.fnmatch(path.name, pattern)
        for pattern in sync_policy.excluded_globs
    ):
        return True
    return bool(sync_policy.max_file_size_bytes and path.stat().st_size > sync_policy.max_file_size_bytes)


def capture_workspace_file_snapshot(
    workspace_root: str | Path | None,
    *,
    policy: WorkspaceSyncPolicy | None = None,
) -> dict[str, tuple[int, int]]:
    if not workspace_root:
        return {}
    root = Path(workspace_root).expanduser().resolve()
    if not root.exists() or not root.is_dir():
        return {}
    sync_policy = policy or WorkspaceSyncPolicy()
    snapshot: dict[str, tuple[int, int]] = {}
    for path in sorted((item for item in root.rglob("*") if item.is_file()), key=lambda item: item.as_posix()):
        if len(snapshot) >= sync_policy.max_file_count:
            break
        if _should_skip_workspace_file(root, path, policy=sync_policy):
            continue
        stat_result = path.stat()
        snapshot[path.relative_to(root).as_posix()] = (stat_result.st_mtime_ns, stat_result.st_size)
    return snapshot


async def sync_workspace_file_after_write(
    *,
    db: AsyncSession | None,
    session_id: str | None,
    workspace_root: str | Path | None,
    file_path: str | Path,
    content_type: str = "application/octet-stream",
    put_object_func=put_workspace_storage_object,
    resolve_config_func=resolve_session_workspace_storage_config,
) -> dict[str, Any]:
    if db is None:
        return {"status": "skipped", "reason": "db_unavailable"}
    if not session_id:
        return {"status": "skipped", "reason": "session_id_unavailable"}
    if not workspace_root:
        return {"status": "skipped", "reason": "workspace_root_unavailable"}

    root = Path(workspace_root).expanduser().resolve()
    target = Path(file_path).expanduser().resolve()
    if not _path_within_root(root, target):
        return {"status": "error", "error": "file_path_outside_workspace"}
    if not target.is_file():
        return {"status": "skipped", "reason": "not_a_file"}

    # Sync is a durability mirror, not the authoritative local write. Failures
    # must be surfaced to the caller without rolling back the local workspace.
    try:
        config = await resolve_config_func(db)
        if not config.enabled:
            return {"status": "skipped", "reason": "storage_disabled"}
        policy = await resolve_workspace_sync_policy(db)
        if _should_skip_workspace_file(root, target, policy=policy):
            return {"status": "skipped", "reason": "excluded_by_sync_policy"}

        session = await db.get(Session, session_id)
        if session is None:
            return {"status": "skipped", "reason": "session_not_found"}

        metadata = get_session_metadata(session)
        if not isinstance(metadata.get(SESSION_WORKSPACE_STORAGE_METADATA_KEY), dict):
            set_session_workspace_storage_metadata(session, config)
            await db.flush()

        relative_path = target.relative_to(root).as_posix()
        object_key = workspace_current_object_key(config, session_id=session_id, relative_path=relative_path)
        payload = target.read_bytes()
        stored = put_object_func(config, object_key=object_key, payload=payload, content_type=content_type)
    except Exception as exc:
        return {"status": "error", "error": error_text("workspace_file_sync_failed", exc)}

    return {
        "status": "synced",
        "backend": config.backend,
        "bucket": config.bucket,
        "key": stored.key,
        "relative_path": relative_path,
        "size_bytes": stored.size_bytes,
    }


async def sync_workspace_files_after_write(
    *,
    db: AsyncSession | None,
    session_id: str | None,
    workspace_root: str | Path | None,
    file_paths: list[str | Path],
    policy: WorkspaceSyncPolicy | None = None,
    resolve_config_func=resolve_session_workspace_storage_config,
) -> dict[str, Any]:
    root = Path(workspace_root or "").expanduser().resolve() if workspace_root else None
    results = [
        await sync_workspace_file_after_write(
            db=db,
            session_id=session_id,
            workspace_root=workspace_root,
            file_path=file_path,
            resolve_config_func=resolve_config_func,
        )
        for file_path in file_paths
        if root is None
        or policy is None
        or not _should_skip_workspace_file(root, Path(file_path).expanduser().resolve(), policy=policy)
    ]
    errors = [item for item in results if item.get("status") == "error"]
    synced = [item for item in results if item.get("status") == "synced"]
    skipped = [item for item in results if item.get("status") == "skipped"]
    if errors:
        return {"status": "error", "synced": len(synced), "skipped": len(skipped), "errors": errors}
    if synced:
        return {"status": "synced", "synced": len(synced), "skipped": len(skipped), "files": synced}
    return skipped[0] if skipped else {"status": "skipped", "reason": "no_files"}


async def sync_workspace_paths_after_delete(
    *,
    db: AsyncSession | None,
    session_id: str | None,
    relative_paths: list[str],
    delete_object_func=delete_workspace_storage_object,
    resolve_config_func=resolve_session_workspace_storage_config,
) -> dict[str, Any]:
    if db is None:
        return {"status": "skipped", "reason": "db_unavailable"}
    if not session_id:
        return {"status": "skipped", "reason": "session_id_unavailable"}
    if not relative_paths:
        return {"status": "skipped", "reason": "no_paths"}

    try:
        config = await resolve_config_func(db)
        if not config.enabled:
            return {"status": "skipped", "reason": "storage_disabled"}

        deleted_keys: list[str] = []
        for relative_path in sorted(set(relative_paths)):
            object_key = workspace_current_object_key(config, session_id=session_id, relative_path=relative_path)
            delete_object_func(config, object_key=object_key)
            deleted_keys.append(object_key)
    except Exception as exc:
        return {"status": "error", "error": error_text("workspace_delete_sync_failed", exc)}

    return {
        "status": "synced",
        "backend": config.backend,
        "bucket": config.bucket,
        "deleted": len(deleted_keys),
        "keys": deleted_keys,
    }


async def sync_workspace_changes_since_snapshot(
    *,
    db: AsyncSession | None,
    session_id: str | None,
    workspace_root: str | Path | None,
    before_snapshot: dict[str, tuple[int, int]],
    policy: WorkspaceSyncPolicy | None = None,
) -> dict[str, Any]:
    if not workspace_root:
        return {"status": "skipped", "reason": "workspace_root_unavailable"}
    root = Path(workspace_root).expanduser().resolve()
    sync_policy = policy or await resolve_workspace_sync_policy(db)
    after_snapshot = capture_workspace_file_snapshot(root, policy=sync_policy)
    changed_relative_paths = [
        relative_path
        for relative_path, state in after_snapshot.items()
        if before_snapshot.get(relative_path) != state
    ]
    deleted_relative_paths = sorted(set(before_snapshot) - set(after_snapshot))
    changed_files = [root / relative_path for relative_path in changed_relative_paths]
    write_sync = await sync_workspace_files_after_write(
        db=db,
        session_id=session_id,
        workspace_root=root,
        file_paths=changed_files,
        policy=sync_policy,
    )
    delete_sync = await sync_workspace_paths_after_delete(
        db=db,
        session_id=session_id,
        relative_paths=deleted_relative_paths,
    )
    if write_sync.get("status") == "error" or delete_sync.get("status") == "error":
        return {"status": "error", "write": write_sync, "delete": delete_sync}
    if changed_relative_paths or deleted_relative_paths:
        return {
            "status": "synced",
            "changed": len(changed_relative_paths),
            "deleted": len(deleted_relative_paths),
            "write": write_sync,
            "delete": delete_sync,
        }
    return {"status": "skipped", "reason": "no_changes"}


async def sync_workspace_full(
    *,
    db: AsyncSession | None,
    session_id: str | None,
    workspace_root: str | Path | None,
    reason: str = "manual",
    put_manifest_func=put_workspace_manifest,
    resolve_config_func=resolve_session_workspace_storage_config,
) -> dict[str, Any]:
    if db is None:
        return {"status": "skipped", "reason": "db_unavailable"}
    if not session_id:
        return {"status": "skipped", "reason": "session_id_unavailable"}
    if not workspace_root:
        return {"status": "skipped", "reason": "workspace_root_unavailable"}

    root = Path(workspace_root).expanduser().resolve()
    if not root.exists() or not root.is_dir():
        return {"status": "skipped", "reason": "workspace_root_unavailable"}

    try:
        config = await resolve_config_func(db)
        if not config.enabled:
            return {"status": "skipped", "reason": "storage_disabled"}

        session = await db.get(Session, session_id)
        if session is None:
            return {"status": "skipped", "reason": "session_not_found"}
        metadata = get_session_metadata(session)
        if not isinstance(metadata.get(SESSION_WORKSPACE_STORAGE_METADATA_KEY), dict):
            set_session_workspace_storage_metadata(session, config)
            await db.flush()

        policy = await resolve_workspace_sync_policy(db)
        snapshot = capture_workspace_file_snapshot(root, policy=policy)
        file_paths = [root / relative_path for relative_path in snapshot]
        write_sync = await sync_workspace_files_after_write(
            db=db,
            session_id=session_id,
            workspace_root=root,
            file_paths=file_paths,
            policy=policy,
            resolve_config_func=resolve_config_func,
        )
        if write_sync.get("status") == "error":
            return {"status": "error", "write": write_sync}

        files = [
            {
                "path": relative_path,
                "size_bytes": state[1],
                "object_key": workspace_current_object_key(
                    config,
                    session_id=session_id,
                    relative_path=relative_path,
                ),
            }
            for relative_path, state in sorted(snapshot.items())
        ]
        manifest = {
            "schema_version": 1,
            "session_id": session_id,
            "backend": config.backend,
            "bucket": config.bucket,
            "prefix": config.prefix,
            "reason": str(reason or "manual").strip() or "manual",
            "synced_at": utc_now_aware().isoformat(),
            "file_count": len(files),
            "files": files,
        }
        manifest_object = put_manifest_func(config, session_id=session_id, manifest=manifest)
    except Exception as exc:
        return {"status": "error", "error": error_text("workspace_full_sync_failed", exc)}

    return {
        "status": "synced",
        "backend": config.backend,
        "bucket": config.bucket,
        "file_count": len(files),
        "manifest_key": manifest_object.key,
        "write": write_sync,
    }


__all__ = [
    "WorkspaceSyncPolicy",
    "capture_workspace_file_snapshot",
    "resolve_workspace_sync_policy",
    "save_workspace_sync_policy_settings",
    "sync_workspace_file_after_write",
    "sync_workspace_files_after_write",
    "sync_workspace_changes_since_snapshot",
    "sync_workspace_full",
    "sync_workspace_paths_after_delete",
]
