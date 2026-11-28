"""Proposed checks: a repeated correction becomes a check a person approves."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession


async def signature_updated(db: AsyncSession, signature: str | dict[str, Any]) -> Any:
    """The signature's proposal after a change (``None`` while it is below the Workspace's threshold).
    ``signature`` is its id (read with ``corrections.get_signature``) or the contract's shape itself."""
    from ...models import Project
    from .store import signature_seen

    if isinstance(signature, str):
        from ..workflow_runs.corrections import get_signature

        found = await get_signature(db, signature)
        if found is None:
            return None
        signature = found
    project = await db.get(Project, str(signature.get("workspace_id") or ""))
    if project is None:
        return None
    return await signature_seen(db, project.id, project.config, signature)


__all__ = ["signature_updated"]
