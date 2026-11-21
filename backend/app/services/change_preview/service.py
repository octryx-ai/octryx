"""Change previews: stored previews and the grants they carry (fingerprints and builders live in other modules)."""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import ChangePreview
from ...time_utils import utc_now, utc_now_aware


def serialize_change_preview(preview: ChangePreview | None) -> dict[str, Any] | None:
    if preview is None:
        return None
    try:
        payload = json.loads(preview.preview_json or "{}")
    except json.JSONDecodeError:
        payload = {"summary": preview.preview_json or ""}
    from ..approval.presentation import readable_plan

    # A write plan's single writes in words (titled when read, ``approval.presentation.readable_plan``).
    payload = readable_plan(payload)
    return {
        "id": preview.id,
        "taskRunId": preview.task_run_id or "",
        "sessionId": preview.session_id or "",
        "approvalId": preview.approval_id or "",
        "toolName": preview.tool_name or "",
        "requestFingerprint": preview.request_fingerprint or "",
        "preview": payload if isinstance(payload, dict) else {"value": payload},
        "acknowledgedBy": preview.acknowledged_by or "",
        "acknowledgedAt": preview.acknowledged_at.isoformat() if preview.acknowledged_at else None,
        "createdAt": preview.created_at.isoformat() if preview.created_at else None,
        "updatedAt": preview.updated_at.isoformat() if preview.updated_at else None,
    }


def offered_decisions(payload: dict[str, Any]) -> list[str]:
    """The decisions the card offers: ``once`` and ``deny`` always, ``always`` only where a
    standing rule may answer this request (its preview names one; never for an external write)."""
    explicit = payload.get("offered_decisions")
    if isinstance(explicit, list) and explicit:
        return [str(item) for item in explicit]
    return ["once", "always", "deny"] if payload.get("standing_rule") else ["once", "deny"]


async def upsert_change_preview(
    db: AsyncSession,
    *,
    tool_name: str,
    preview_payload: dict[str, Any],
    request_fingerprint: str,
    task_run_id: str | None = None,
    session_id: str | None = None,
    approval_id: str | None = None,
) -> ChangePreview:
    query = select(ChangePreview).where(
        ChangePreview.tool_name == tool_name,
        ChangePreview.request_fingerprint == request_fingerprint,
    )
    if approval_id:
        query = query.where(ChangePreview.approval_id == approval_id)
    elif session_id:
        query = query.where(ChangePreview.session_id == session_id, ChangePreview.approval_id.is_(None))
    existing = (await db.execute(query.order_by(ChangePreview.created_at.desc()))).scalars().first()
    from ..secret_masking import mask_payload

    # Stored masked like transcripts: a preview carries model-written values (an sk- token in a body).
    preview_payload = {**preview_payload, "offered_decisions": offered_decisions(preview_payload)}
    serialized_payload = json.dumps(mask_payload(preview_payload), ensure_ascii=False)
    if existing is not None:
        existing.preview_json = serialized_payload
        existing.task_run_id = task_run_id or existing.task_run_id
        existing.session_id = session_id or existing.session_id
        existing.approval_id = approval_id or existing.approval_id
        existing.updated_at = utc_now()
        await db.flush()
        return existing

    preview = ChangePreview(
        tool_name=tool_name,
        task_run_id=task_run_id,
        session_id=session_id,
        approval_id=approval_id,
        request_fingerprint=request_fingerprint,
        preview_json=serialized_payload,
    )
    db.add(preview)
    await db.flush()
    return preview


async def list_change_previews_by_approval_id(
    db: AsyncSession,
    approval_ids: list[str],
) -> dict[str, ChangePreview]:
    if not approval_ids:
        return {}
    previews = (
        (
            await db.execute(
                select(ChangePreview)
                .where(ChangePreview.approval_id.in_(approval_ids))
                .order_by(ChangePreview.created_at.desc())
            )
        )
        .scalars()
        .all()
    )
    result: dict[str, ChangePreview] = {}
    for preview in previews:
        result.setdefault(str(preview.approval_id or ""), preview)
    return result


async def acknowledge_change_previews_for_approval(
    db: AsyncSession,
    *,
    approval_id: str,
    acknowledged_by: str,
) -> None:
    previews = (await db.execute(select(ChangePreview).where(ChangePreview.approval_id == approval_id))).scalars().all()
    now = utc_now()
    for preview in previews:
        preview.acknowledged_by = acknowledged_by
        preview.acknowledged_at = now
        preview.updated_at = now
    await db.flush()


async def approval_grants_from_preview(
    db: AsyncSession,
    *,
    approval_id: str,
) -> list[dict[str, Any]]:
    previews = (await db.execute(select(ChangePreview).where(ChangePreview.approval_id == approval_id))).scalars().all()
    grants: list[dict[str, Any]] = []
    for preview in previews:
        grants.append(
            {
                "approval_id": approval_id,
                "tool_name": preview.tool_name,
                "request_fingerprint": preview.request_fingerprint,
                "created_at": utc_now_aware().isoformat(),
            }
        )
    return grants


__all__ = [
    "acknowledge_change_previews_for_approval",
    "approval_grants_from_preview",
    "list_change_previews_by_approval_id",
    "offered_decisions",
    "serialize_change_preview",
    "upsert_change_preview",
]
