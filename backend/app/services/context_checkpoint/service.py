"""Session-scoped context freeze / checkpoint helpers."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import ContextCheckpoint
from ...services.prompt_catalog import render_prompt
from ...time_utils import utc_now

ACTIVE_STATUS = "active"
RELEASED_STATUS = "released"
ROLLED_BACK_STATUS = "rolled_back"
ALLOWED_RELEASE_ACTIONS = {"release": RELEASED_STATUS, "rollback": ROLLED_BACK_STATUS}


def _clean_checkpoint_name(value: str | None) -> str:
    cleaned = str(value or "").strip()
    return cleaned[:200] or "checkpoint"


def _snapshot_copy(snapshot: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(snapshot, dict):
        return {}
    return dict(snapshot)


async def get_active_context_checkpoint(
    db: AsyncSession,
    *,
    session_id: str | None,
) -> ContextCheckpoint | None:
    if not session_id:
        return None
    result = await db.execute(
        select(ContextCheckpoint)
        .where(
            ContextCheckpoint.session_id == session_id,
            ContextCheckpoint.status == ACTIVE_STATUS,
        )
        .order_by(ContextCheckpoint.created_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def list_context_checkpoints(
    db: AsyncSession,
    *,
    session_id: str,
    limit: int = 20,
) -> list[ContextCheckpoint]:
    result = await db.execute(
        select(ContextCheckpoint)
        .where(ContextCheckpoint.session_id == session_id)
        .order_by(ContextCheckpoint.created_at.desc())
        .limit(max(1, min(int(limit or 20), 100)))
    )
    return list(result.scalars().all())


async def create_context_checkpoint(
    db: AsyncSession,
    *,
    session_id: str,
    checkpoint_name: str | None,
    context_snapshot: dict[str, Any] | None,
) -> ContextCheckpoint:
    active = await get_active_context_checkpoint(db, session_id=session_id)
    if active is not None:
        raise ValueError(f"Context is already frozen under checkpoint '{active.checkpoint_name}'.")
    checkpoint = ContextCheckpoint(
        session_id=session_id,
        checkpoint_name=_clean_checkpoint_name(checkpoint_name),
        context_snapshot_json=_snapshot_copy(context_snapshot),
        status=ACTIVE_STATUS,
    )
    db.add(checkpoint)
    await db.commit()
    await db.refresh(checkpoint)
    return checkpoint


async def release_context_checkpoint(
    db: AsyncSession,
    *,
    session_id: str,
    checkpoint_name: str | None = None,
    action: str = "release",
) -> ContextCheckpoint:
    target_status = ALLOWED_RELEASE_ACTIONS.get(str(action or "").strip().lower())
    if not target_status:
        raise ValueError("action must be 'release' or 'rollback'")

    active = await get_active_context_checkpoint(db, session_id=session_id)
    if active is None:
        raise ValueError("No active context checkpoint found.")
    if checkpoint_name and _clean_checkpoint_name(checkpoint_name) != active.checkpoint_name:
        raise ValueError(
            f"Active checkpoint is '{active.checkpoint_name}', not '{_clean_checkpoint_name(checkpoint_name)}'."
        )
    active.status = target_status
    active.released_at = utc_now()
    await db.commit()
    await db.refresh(active)
    return active


def render_context_checkpoint_for_prompt(checkpoint: ContextCheckpoint | None) -> str:
    if checkpoint is None:
        return ""
    return render_prompt("context.checkpoint.section", checkpoint_name=checkpoint.checkpoint_name)
