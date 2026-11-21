"""Repository sync planning for native Code Graph indexing."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import CodeGraphFile, CodeGraphRepository
from app.services.code_intelligence.storage_search import _iter_source_files, _language_for_path


def build_repository_file_manifest(repo_root: Path) -> dict[str, dict[str, Any]]:
    manifest: dict[str, dict[str, Any]] = {}
    for path in _iter_source_files(repo_root):
        try:
            raw = path.read_bytes()
            stat = path.stat()
        except OSError:
            continue
        relative_path = str(path.relative_to(repo_root))
        manifest[relative_path] = {
            "path": relative_path,
            "language": _language_for_path(path) or "unknown",
            "file_hash": hashlib.sha256(raw).hexdigest(),
            "mtime_ns": int(stat.st_mtime_ns),
            "size_bytes": int(stat.st_size),
        }
    return manifest


async def build_code_graph_sync_plan(
    *,
    db: AsyncSession,
    repository_id: str,
    repo_root: Path,
    force: bool = False,
) -> dict[str, Any]:
    current = build_repository_file_manifest(repo_root)
    graph_repo = (
        await db.execute(select(CodeGraphRepository).where(CodeGraphRepository.code_repository_id == repository_id))
    ).scalar_one_or_none()
    previous = await _latest_indexed_manifest(db=db, graph_repo=graph_repo)
    added = sorted(path for path in current if path not in previous)
    deleted = sorted(path for path in previous if path not in current)
    modified = sorted(
        path
        for path, current_item in current.items()
        if path in previous and _file_changed(current_item, previous[path])
    )
    unchanged = sorted(path for path in current if path in previous and path not in modified)
    has_previous = bool(previous)
    has_changes = bool(force or added or modified or deleted or not has_previous)
    return {
        "status": "changed" if has_changes else "fresh",
        "indexing_mode": "full" if force or not has_previous else "incremental",
        "force": bool(force),
        "has_previous_graph": has_previous,
        "has_changes": has_changes,
        "files_checked": len(current),
        "files_added": len(added),
        "files_modified": len(modified),
        "files_deleted": len(deleted),
        "files_unchanged": len(unchanged),
        "files_to_index": len(added) + len(modified),
        "files_errored": sum(1 for item in previous.values() if item.get("parse_error")),
        "added_paths": added,
        "modified_paths": modified,
        "deleted_paths": deleted,
        "unchanged_paths_sample": unchanged[:25],
        "staleness_warnings": _staleness_warnings(added=added, modified=modified, deleted=deleted),
    }


async def update_graph_repository_staleness_from_plan(
    *,
    db: AsyncSession,
    repository_id: str,
    plan: dict[str, Any],
) -> None:
    graph_repo = (
        await db.execute(select(CodeGraphRepository).where(CodeGraphRepository.code_repository_id == repository_id))
    ).scalar_one_or_none()
    if graph_repo is None:
        return
    if bool(plan.get("has_changes")):
        graph_repo.staleness_state = "stale"
        graph_repo.backend_metadata = {
            **(graph_repo.backend_metadata or {}),
            "pending_sync": _plan_summary(plan),
        }
    else:
        graph_repo.staleness_state = "fresh"
        graph_repo.backend_metadata = {
            **(graph_repo.backend_metadata or {}),
            "pending_sync": {},
        }
    await db.flush()


async def load_graph_staleness_warnings(
    *,
    db: AsyncSession,
    repository_id: str,
    repo_root: Path,
) -> dict[str, Any]:
    plan = await build_code_graph_sync_plan(db=db, repository_id=repository_id, repo_root=repo_root, force=False)
    return {
        "state": "stale" if plan.get("has_changes") else "fresh",
        "warnings": plan.get("staleness_warnings") or [],
        "summary": _plan_summary(plan),
    }


def _file_changed(current: dict[str, Any], previous: dict[str, Any]) -> bool:
    current_hash = str(current.get("file_hash") or "")
    previous_hash = str(previous.get("file_hash") or "")
    if current_hash and previous_hash:
        return current_hash != previous_hash
    return (
        int(current.get("mtime_ns") or 0) != int(previous.get("mtime_ns") or 0)
        or int(current.get("size_bytes") or 0) != int(previous.get("size_bytes") or 0)
    )


async def _latest_indexed_manifest(
    *, db: AsyncSession, graph_repo: CodeGraphRepository | None
) -> dict[str, dict[str, Any]]:
    if graph_repo is None or not graph_repo.latest_run_id:
        return {}
    rows = (
        await db.execute(
            select(CodeGraphFile).where(
                CodeGraphFile.run_id == graph_repo.latest_run_id,
                CodeGraphFile.is_current.is_(True),
            )
        )
    ).scalars().all()
    return {
        row.file_path: {
            "path": row.file_path,
            "language": row.language,
            "file_hash": row.file_hash,
            "mtime_ns": row.mtime_ns,
            "size_bytes": row.size_bytes,
            "parse_error": row.parse_error,
        }
        for row in rows
    }


def _staleness_warnings(*, added: list[str], modified: list[str], deleted: list[str]) -> list[dict[str, Any]]:
    warnings: list[dict[str, Any]] = []
    for status, paths in (("added", added), ("modified", modified), ("deleted", deleted)):
        for path in paths[:25]:
            warnings.append(
                {
                    "path": path,
                    "status": status,
                    "message": f"{path} is {status} on disk and has not been re-indexed yet.",
                }
            )
    return warnings


def _plan_summary(plan: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": plan.get("status"),
        "indexing_mode": plan.get("indexing_mode"),
        "files_checked": int(plan.get("files_checked") or 0),
        "files_added": int(plan.get("files_added") or 0),
        "files_modified": int(plan.get("files_modified") or 0),
        "files_deleted": int(plan.get("files_deleted") or 0),
        "files_unchanged": int(plan.get("files_unchanged") or 0),
        "files_to_index": int(plan.get("files_to_index") or 0),
        "files_errored": int(plan.get("files_errored") or 0),
    }


__all__ = [
    "build_code_graph_sync_plan",
    "build_repository_file_manifest",
    "load_graph_staleness_warnings",
    "update_graph_repository_staleness_from_plan",
]
