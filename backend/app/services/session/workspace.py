from __future__ import annotations

import asyncio
import logging
import os
import re
import shutil
import tempfile
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ...models import Session
from ...time_utils import utc_now, utc_now_aware
from ..background_worker_state import (
    record_background_worker_failure,
    record_background_worker_success,
)
from ..system_config import get_system_config_value, set_system_config_value
from .shared import get_session_metadata_text, set_session_metadata_value
from .workspace_restore import restore_session_workspace_from_storage
from .workspace_sync import sync_workspace_files_after_write, sync_workspace_paths_after_delete
from .workspace_tree import (
    search_workspace_entries,
    serialize_workspace_children,
)
from .workspace_tree import (
    workspace_entry_for_path as build_workspace_entry_for_path,
)

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_SESSION_WORKSPACE_BASE_DIR = (Path(tempfile.gettempdir()) / "octryx-session-workspaces").resolve()
DEFAULT_SESSION_WORKSPACE_MAX_AGE_HOURS = 24
SESSION_WORKSPACE_METADATA_KEY = "workspace_root"
AGENT_SESSION_WORKSPACE_BASE_DIR_KEY = "agent.session_workspace_base_dir"
AGENT_SESSION_WORKSPACE_MAX_AGE_HOURS_KEY = "agent.session_workspace_max_age_hours"
SESSION_WORKSPACE_BASE_DIR_ENV = "OCTRYX_SESSION_WORKSPACE_BASE_DIR"
SESSION_WORKSPACE_MAX_AGE_HOURS_ENV = "OCTRYX_SESSION_WORKSPACE_MAX_AGE_HOURS"
_SAFE_SEGMENT_PATTERN = re.compile(r"[^A-Za-z0-9._-]+")


def _safe_segment(value: str) -> str:
    cleaned = _SAFE_SEGMENT_PATTERN.sub("-", str(value or "").strip()).strip("-.")
    return cleaned or "session"


def _get_configured_workspace_root(session: Session) -> Path | None:
    configured = get_session_metadata_text(session, SESSION_WORKSPACE_METADATA_KEY)
    if not configured:
        return None
    return Path(configured).expanduser().resolve()


def _set_configured_workspace_root(session: Session, root: Path) -> None:
    set_session_metadata_value(session, SESSION_WORKSPACE_METADATA_KEY, str(root))


def _normalize_base_dir(raw_value: str | None) -> Path:
    text = str(raw_value or "").strip()
    candidate = Path(text).expanduser() if text else DEFAULT_SESSION_WORKSPACE_BASE_DIR
    resolved = candidate.resolve() if candidate.is_absolute() else (REPO_ROOT / candidate).resolve()
    resolved.mkdir(parents=True, exist_ok=True)
    return resolved


def _bounded_hours(raw_value: str | None) -> int:
    try:
        parsed = int(str(raw_value or "").strip())
    except (TypeError, ValueError):
        parsed = DEFAULT_SESSION_WORKSPACE_MAX_AGE_HOURS
    return max(0, min(parsed, 24 * 365))


def _build_session_workspace_root(base_dir: Path, session_id: str) -> Path:
    root = (base_dir / _safe_segment(session_id)).resolve()
    if base_dir not in root.parents and root != base_dir:
        raise ValueError("Session workspace must stay inside the configured base directory")
    return root


def _ensure_path_within_root(root: Path, candidate: Path, *, error_message: str) -> Path:
    resolved = candidate.resolve()
    if root not in resolved.parents and resolved != root:
        raise ValueError(error_message)
    return resolved


def _resolve_workspace_path(workspace_root: Path, requested_path: str) -> Path:
    root = workspace_root.resolve()
    raw = str(requested_path or "").strip()
    candidate = Path(raw).expanduser() if raw else root
    if not candidate.is_absolute():
        candidate = root / candidate
    return _ensure_path_within_root(root, candidate, error_message="Path must stay inside the session workspace")


def _remove_workspace_artifact(target: Path) -> None:
    if target.is_dir():
        shutil.rmtree(target)
        return
    target.unlink(missing_ok=True)


def _workspace_file_paths(target: Path) -> list[Path]:
    if target.is_file():
        return [target]
    if target.is_dir():
        return sorted((item for item in target.rglob("*") if item.is_file()), key=lambda item: item.as_posix())
    return []


def _relative_workspace_file_paths(workspace_root: Path, target: Path) -> list[str]:
    root = workspace_root.resolve()
    return [item.relative_to(root).as_posix() for item in _workspace_file_paths(target)]


def _log_workspace_sync_error(action: str, result: dict[str, Any]) -> None:
    if result.get("status") == "error":
        logger.warning("Session workspace %s sync failed: %s", action, result.get("error") or result.get("errors"))


async def get_session_workspace_base_dir(db: AsyncSession) -> Path:
    configured = await get_system_config_value(db, AGENT_SESSION_WORKSPACE_BASE_DIR_KEY)
    return _normalize_base_dir(configured or os.environ.get(SESSION_WORKSPACE_BASE_DIR_ENV))


async def get_session_workspace_max_age_hours(db: AsyncSession) -> int:
    configured = await get_system_config_value(db, AGENT_SESSION_WORKSPACE_MAX_AGE_HOURS_KEY)
    return _bounded_hours(configured or os.environ.get(SESSION_WORKSPACE_MAX_AGE_HOURS_ENV))


async def resolve_session_workspace_root(
    db: AsyncSession,
    session: Session,
    *,
    create: bool = True,
) -> Path:
    root = _get_configured_workspace_root(session)
    if root is None:
        base_dir = await get_session_workspace_base_dir(db)
        root = _build_session_workspace_root(base_dir, session.id)
    if create:
        root.mkdir(parents=True, exist_ok=True)
    return root


async def ensure_session_workspace_root(
    db: AsyncSession,
    session: Session,
    *,
    create: bool = True,
) -> Path:
    root = await resolve_session_workspace_root(db, session, create=create)
    if _get_configured_workspace_root(session) is None:
        _set_configured_workspace_root(session, root)
        await db.flush()
    if create:
        restore_result = await restore_session_workspace_from_storage(db=db, session=session, workspace_root=root)
        _log_workspace_sync_error("restore", restore_result)
    return root


async def get_session_workspace_root(
    db: AsyncSession,
    session_id: str,
    *,
    create: bool = True,
) -> Path:
    session = await db.get(Session, session_id)
    if session is None:
        raise ValueError(f"Unknown session: {session_id}")
    return await ensure_session_workspace_root(db, session, create=create)


def ensure_workspace_path(workspace_root: Path, requested_path: str) -> Path:
    return _resolve_workspace_path(workspace_root, requested_path)


def workspace_entry_for_path(workspace_root: Path, path: Path) -> dict[str, Any]:
    return build_workspace_entry_for_path(workspace_root, path)


def serialize_session_workspace_children(
    workspace_root: Path,
    *,
    relative_path: str = "",
) -> list[dict[str, Any]]:
    root = workspace_root.resolve()
    if not root.exists():
        return []
    target = ensure_workspace_path(root, relative_path)
    return serialize_workspace_children(root, target)


def search_session_workspace_entries(
    workspace_root: Path,
    *,
    query: str,
    limit: int = 200,
) -> list[dict[str, Any]]:
    return search_workspace_entries(workspace_root, query=query, limit=limit)


async def create_workspace_directory(db: AsyncSession, session_id: str, relative_path: str) -> Path:
    workspace_root = await get_session_workspace_root(db, session_id)
    target = ensure_workspace_path(workspace_root, relative_path)
    target.mkdir(parents=True, exist_ok=True)
    return target


async def rename_workspace_path(db: AsyncSession, session_id: str, path: str, new_name: str) -> Path:
    workspace_root = await get_session_workspace_root(db, session_id)
    source = ensure_workspace_path(workspace_root, path)
    if not source.exists():
        raise FileNotFoundError(path)
    safe_name = _safe_segment(new_name)
    if not safe_name:
        raise ValueError("New name is required")
    target = _ensure_path_within_root(
        workspace_root.resolve(),
        source.with_name(safe_name),
        error_message="Target must stay inside the workspace",
    )
    if target.exists():
        raise FileExistsError(str(target))
    old_relative_paths = _relative_workspace_file_paths(workspace_root, source)
    source.rename(target)
    write_sync = await sync_workspace_files_after_write(
        db=db,
        session_id=session_id,
        workspace_root=workspace_root,
        file_paths=_workspace_file_paths(target),
    )
    delete_sync = await sync_workspace_paths_after_delete(
        db=db,
        session_id=session_id,
        relative_paths=old_relative_paths,
    )
    _log_workspace_sync_error("rename write", write_sync)
    _log_workspace_sync_error("rename delete", delete_sync)
    return target


async def move_workspace_paths(
    db: AsyncSession,
    session_id: str,
    paths: list[str],
    target_directory: str,
) -> list[Path]:
    workspace_root = await get_session_workspace_root(db, session_id)
    destination_dir = ensure_workspace_path(workspace_root, target_directory)
    destination_dir.mkdir(parents=True, exist_ok=True)
    moved: list[Path] = []
    for raw_path in paths:
        source = ensure_workspace_path(workspace_root, raw_path)
        if not source.exists():
            continue
        target = _ensure_path_within_root(
            workspace_root.resolve(),
            destination_dir / source.name,
            error_message="Move target must stay inside the workspace",
        )
        if target.exists():
            raise FileExistsError(str(target))
        old_relative_paths = _relative_workspace_file_paths(workspace_root, source)
        source.rename(target)
        write_sync = await sync_workspace_files_after_write(
            db=db,
            session_id=session_id,
            workspace_root=workspace_root,
            file_paths=_workspace_file_paths(target),
        )
        delete_sync = await sync_workspace_paths_after_delete(
            db=db,
            session_id=session_id,
            relative_paths=old_relative_paths,
        )
        _log_workspace_sync_error("move write", write_sync)
        _log_workspace_sync_error("move delete", delete_sync)
        moved.append(target)
    return moved


async def delete_workspace_paths(db: AsyncSession, session_id: str, paths: list[str]) -> int:
    workspace_root = await get_session_workspace_root(db, session_id)
    deleted = 0
    targets = sorted(
        {ensure_workspace_path(workspace_root, raw_path) for raw_path in paths},
        key=lambda item: len(item.parts),
        reverse=True,
    )
    for target in targets:
        if not target.exists() or target == workspace_root:
            continue
        old_relative_paths = _relative_workspace_file_paths(workspace_root, target)
        _remove_workspace_artifact(target)
        delete_sync = await sync_workspace_paths_after_delete(
            db=db,
            session_id=session_id,
            relative_paths=old_relative_paths,
        )
        _log_workspace_sync_error("delete", delete_sync)
        deleted += 1
    return deleted


async def clean_session_workspace(db: AsyncSession, session_id: str) -> dict[str, Any]:
    workspace_root = await get_session_workspace_root(db, session_id)
    removed = 0
    for child in list(workspace_root.iterdir()):
        old_relative_paths = _relative_workspace_file_paths(workspace_root, child)
        _remove_workspace_artifact(child)
        delete_sync = await sync_workspace_paths_after_delete(
            db=db,
            session_id=session_id,
            relative_paths=old_relative_paths,
        )
        _log_workspace_sync_error("clean", delete_sync)
        removed += 1
    return {"rootPath": str(workspace_root), "removed": removed}


async def delete_session_workspace(db: AsyncSession, session_id: str) -> bool:
    try:
        workspace_root = await get_session_workspace_root(db, session_id, create=False)
    except ValueError:
        base_dir = await get_session_workspace_base_dir(db)
        workspace_root = _build_session_workspace_root(base_dir, session_id)
    if workspace_root.exists():
        shutil.rmtree(workspace_root, ignore_errors=True)
        return True
    return False


async def _holds_open_run_copy(db: AsyncSession, session_id: str) -> bool:
    """True while the session is bound to a workflow run that has not ended (its working copy is in this folder)."""
    from ...models import WorkflowRun, WorkflowRunSession
    from ..workflow_runs.states import TERMINAL_STATUSES

    row = (await db.execute(
        select(WorkflowRunSession.id)
        .join(WorkflowRun, WorkflowRun.id == WorkflowRunSession.run_id)
        .where(WorkflowRunSession.session_id == session_id, WorkflowRun.status.not_in(tuple(TERMINAL_STATUSES)))
        .limit(1)
    )).first()
    return row is not None


async def cleanup_expired_session_workspaces(db: AsyncSession) -> dict[str, Any]:
    max_age_hours = await get_session_workspace_max_age_hours(db)
    base_dir = await get_session_workspace_base_dir(db)
    if max_age_hours <= 0 or not base_dir.exists():
        return {
            "baseDir": str(base_dir),
            "maxAgeHours": max_age_hours,
            "deleted": [],
            "skipped": [],
        }
    cutoff = utc_now_aware().timestamp() - (max_age_hours * 3600)
    deleted: list[str] = []
    skipped: list[str] = []
    for entry in sorted(base_dir.iterdir(), key=lambda item: item.name.lower()):
        if not entry.is_dir():
            continue
        try:
            stat_result = entry.stat()
        except OSError:
            continue
        if stat_result.st_mtime >= cutoff:
            continue
        session = await db.get(Session, entry.name)
        if session and str(session.status or "").strip().lower() in {
            "running",
            "pending_approval",
            "awaiting_subagents",
        }:
            skipped.append(entry.name)
            continue
        if session and await _holds_open_run_copy(db, session.id):
            skipped.append(entry.name)  # a workflow run's working copy lives here until the run ends
            continue
        shutil.rmtree(entry, ignore_errors=True)
        deleted.append(entry.name)
    return {
        "baseDir": str(base_dir),
        "maxAgeHours": max_age_hours,
        "deleted": deleted,
        "skipped": skipped,
    }


class SessionWorkspaceCleanupWorker:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession], interval_seconds: int = 3600) -> None:
        self._session_factory = session_factory
        self._interval_seconds = max(300, int(interval_seconds))
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._run_loop(), name="session-workspace-cleanup")

    async def stop(self) -> None:
        if self._task is None:
            return
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        self._task = None

    async def run_once(self) -> dict[str, Any]:
        started_at = utc_now()
        try:
            async with self._session_factory() as db:
                result = await cleanup_expired_session_workspaces(db)
            await record_background_worker_success(
                self._session_factory,
                worker_name="session_workspace_cleanup_worker",
                owner="sessions",
                started_at=started_at,
                result=result,
            )
            return result
        except Exception as exc:
            await record_background_worker_failure(
                self._session_factory,
                worker_name="session_workspace_cleanup_worker",
                owner="sessions",
                started_at=started_at,
                error=exc,
            )
            raise

    async def _run_loop(self) -> None:
        while True:
            try:
                await self.run_once()
            except Exception:
                logger.exception("Session workspace cleanup failed")
            await asyncio.sleep(self._interval_seconds)


async def save_session_workspace_settings(
    db: AsyncSession,
    *,
    base_dir: str | None = None,
    max_age_hours: int | None = None,
) -> None:
    if base_dir is not None:
        normalized = str(base_dir or "").strip()
        await set_system_config_value(
            db,
            key=AGENT_SESSION_WORKSPACE_BASE_DIR_KEY,
            value=str(_normalize_base_dir(normalized)),
            description="Base directory used for isolated per-session workspaces.",
        )
    if max_age_hours is not None:
        value = _bounded_hours(str(max_age_hours))
        await set_system_config_value(
            db,
            key=AGENT_SESSION_WORKSPACE_MAX_AGE_HOURS_KEY,
            value=str(value),
            description="Maximum age in hours before temporary session workspaces are cleaned up.",
        )
