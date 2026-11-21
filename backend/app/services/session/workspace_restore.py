"""Session workspace restore helpers."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ...models import Session
from ..error_facts import error_text
from .workspace_storage import (
    SESSION_WORKSPACE_STORAGE_METADATA_KEY,
    get_workspace_storage_object,
    list_workspace_storage_objects,
    resolve_session_workspace_storage_config,
    session_workspace_object_prefix,
    set_session_workspace_storage_metadata,
)


def _path_within_root(root: Path, candidate: Path) -> bool:
    resolved_root = root.resolve()
    resolved_candidate = candidate.resolve()
    return resolved_candidate == resolved_root or resolved_root in resolved_candidate.parents


def _workspace_has_local_content(workspace_root: Path) -> bool:
    return workspace_root.exists() and any(workspace_root.iterdir())


async def restore_session_workspace_from_storage(
    *,
    db: AsyncSession,
    session: Session,
    workspace_root: str | Path,
    resolve_config_func=resolve_session_workspace_storage_config,
    list_objects_func=list_workspace_storage_objects,
    get_object_func=get_workspace_storage_object,
) -> dict[str, Any]:
    root = Path(workspace_root).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    if _workspace_has_local_content(root):
        return {"status": "skipped", "reason": "local_workspace_not_empty"}

    try:
        config = await resolve_config_func(db)
        if not config.enabled:
            return {"status": "skipped", "reason": "storage_disabled"}

        current_prefix = f"{session_workspace_object_prefix(config, session_id=session.id)}/workspace/current"
        objects = list_objects_func(config, object_prefix=current_prefix)
        restored: list[str] = []
        for item in objects:
            key = str(item.key or "")
            if not key.startswith(f"{current_prefix}/"):
                continue
            relative_path = key.removeprefix(f"{current_prefix}/")
            target = (root / relative_path).resolve()
            if not _path_within_root(root, target):
                raise ValueError("Restored workspace path must stay inside the session workspace")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(get_object_func(config, object_key=key))
            restored.append(relative_path)

        if restored and not isinstance((session.metadata_ or {}).get(SESSION_WORKSPACE_STORAGE_METADATA_KEY), dict):
            set_session_workspace_storage_metadata(session, config)
            await db.flush()
    except Exception as exc:
        return {"status": "error", "error": error_text("workspace_restore_failed", exc)}

    if not restored:
        return {"status": "skipped", "reason": "no_remote_workspace"}
    return {
        "status": "restored",
        "backend": config.backend,
        "bucket": config.bucket,
        "file_count": len(restored),
        "files": restored,
    }


__all__ = ["restore_session_workspace_from_storage"]
