"""Snapshot-related workspace tools."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.tools.context import ToolContext

from ._code_common import _truncate


async def _get_snapshot_service(context: ToolContext) -> Any:
    """Lazy-import SnapshotService and return an instance for this session."""
    from ...services.snapshot import SnapshotService

    session_id = str(context.session_id or "default")
    workspace = str(context.workspace_root or Path.cwd())
    service = SnapshotService(session_id=session_id, worktree=workspace)
    await service.init()
    return service


class SnapshotCreateTool:
    name = "snapshot_create"
    description = (
        "Save the current workspace state as a named snapshot. "
        "Returns a SHA that can be used to restore or diff later. "
        "Call this before making risky changes so you can roll back."
    )

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        label = str(params.get("label") or "snapshot")
        try:
            service = await _get_snapshot_service(context)
            sha = await service.track(label=label)
        except Exception as exc:
            return {"error": str(exc)}

        if context.db and context.session_id:
            try:
                import datetime

                from sqlalchemy import select

                from ...models import Session

                result = await context.db.execute(select(Session).where(Session.id == context.session_id))
                session = result.scalar_one_or_none()
                if session:
                    metadata = dict(session.metadata_ or {})
                    snapshots = list(metadata.get("snapshots") or [])
                    snapshots.append({"sha": sha, "label": label, "timestamp": datetime.datetime.utcnow().isoformat()})
                    metadata["snapshots"] = snapshots
                    session.metadata_ = metadata
                    await context.db.commit()
            except Exception:
                pass

        return {"sha": sha, "label": label, "status": "created"}


class SnapshotRestoreTool:
    name = "snapshot_restore"
    description = (
        "Restore the workspace to a previously saved snapshot by SHA. "
        "WARNING: This overwrites all current workspace changes. "
        "Use snapshot_diff first to review what will change."
    )

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        sha = str(params.get("sha") or "").strip()
        if not sha:
            return {"error": "sha is required"}
        try:
            service = await _get_snapshot_service(context)
            await service.restore(sha)
        except Exception as exc:
            return {"error": str(exc)}
        return {"sha": sha, "status": "restored"}


class SnapshotDiffTool:
    name = "snapshot_diff"
    description = (
        "Show the diff between a saved snapshot and the current workspace state. "
        "Returns unified diff output (max 8000 chars)."
    )

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        sha = str(params.get("sha") or "").strip()
        if not sha:
            return {"error": "sha is required"}
        try:
            service = await _get_snapshot_service(context)
            diff = await service.diff(sha)
        except Exception as exc:
            return {"error": str(exc)}
        return {"sha": sha, "diff": _truncate(diff)}


class SnapshotListTool:
    name = "snapshot_list"
    description = (
        "List all snapshots saved during this agent session. Returns SHA, label, and timestamp for each snapshot."
    )

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        snapshots = []
        if context.db and context.session_id:
            try:
                from sqlalchemy import select

                from ...models import Session

                result = await context.db.execute(select(Session).where(Session.id == context.session_id))
                session = result.scalar_one_or_none()
                if session:
                    snapshots = list((session.metadata_ or {}).get("snapshots") or [])
            except Exception:
                pass
        return {"snapshots": snapshots, "count": len(snapshots)}


class SnapshotDiffStructuredTool:
    name = "snapshot_diff_structured"
    description = (
        "Return a structured per-file diff between a snapshot and the current workspace. "
        "Each file entry includes status (added/deleted/modified), before/after content, "
        "and addition/deletion line counts. More useful than snapshot_diff for programmatic analysis."
    )

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        sha = str(params.get("sha") or "").strip()
        if not sha:
            return {"error": "sha is required"}
        try:
            service = await _get_snapshot_service(context)
            file_diffs = await service.diff_structured(sha)
        except Exception as exc:
            return {"error": str(exc)}
        return {"sha": sha, "files": [diff.to_dict() for diff in file_diffs], "count": len(file_diffs)}


class SnapshotDiffRangeTool:
    name = "snapshot_diff_range"
    description = (
        "Return a structured per-file diff between two snapshot SHAs. "
        "Useful for reviewing what changed between two checkpoints."
    )

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        sha_from = str(params.get("sha_from") or "").strip()
        sha_to = str(params.get("sha_to") or "").strip()
        if not sha_from or not sha_to:
            return {"error": "sha_from and sha_to are required"}
        try:
            service = await _get_snapshot_service(context)
            file_diffs = await service.diff_range(sha_from, sha_to)
        except Exception as exc:
            return {"error": str(exc)}
        return {
            "sha_from": sha_from,
            "sha_to": sha_to,
            "files": [diff.to_dict() for diff in file_diffs],
            "count": len(file_diffs),
        }
