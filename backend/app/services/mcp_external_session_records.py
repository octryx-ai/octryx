"""The usage records and transcript messages of an ingested external agent session."""

from __future__ import annotations

import re
import uuid
from typing import Any

from fastapi import HTTPException
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Message, Session, UsageEvent, User, WorkItem
from .budget import compute_usage_event_cost
from .error_facts import error_text

MAX_USAGE_RECORDS = 50


def _normalized_usage_records(raw: Any) -> list[dict[str, Any]]:
    if not isinstance(raw, list):
        return []
    if len(raw) > MAX_USAGE_RECORDS:
        raise HTTPException(status_code=400, detail=f"At most {MAX_USAGE_RECORDS} usage records per ingest")
    records: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        model = str(item.get("model") or "").strip()
        if not model:
            raise HTTPException(status_code=400, detail="Every usage record requires a model")
        records.append(
            {
                "model": model,
                "tokens_in": max(0, int(item.get("input_tokens") or 0)),
                "tokens_out": max(0, int(item.get("output_tokens") or 0)),
                "reported_cost_usd": item.get("cost_usd"),
                "cache_read_tokens": max(0, int(item.get("cache_read_tokens") or 0)),
                "cache_creation_tokens": max(0, int(item.get("cache_creation_tokens") or 0)),
            }
        )
    return records


async def _record_usage_events(
    db: AsyncSession,
    *,
    session: Session,
    user: User,
    client: str,
    usage_records: list[dict[str, Any]],
) -> list[str]:
    usage_event_ids: list[str] = []
    for record in usage_records:
        # Platform-side pricing keeps external and internal costs consistent;
        # the client-reported figure is advisory metadata only.
        cost = await compute_usage_event_cost(
            db,
            provider=client,
            model=record["model"],
            tokens_in=record["tokens_in"],
            tokens_out=record["tokens_out"],
            cache_read_tokens=record["cache_read_tokens"],
            cache_creation_tokens=record["cache_creation_tokens"],
        )
        event = UsageEvent(
            id=str(uuid.uuid4()),
            session_id=session.id,
            user_id=user.id,
            provider=client,
            model=record["model"],
            tokens_in=record["tokens_in"],
            tokens_out=record["tokens_out"],
            cache_read_tokens=record["cache_read_tokens"] or None,
            cache_creation_tokens=record["cache_creation_tokens"] or None,
            cost=cost,
        )
        db.add(event)
        usage_event_ids.append(event.id)
    return usage_event_ids


_ROLE_MARKER = re.compile(r"\[(USER|ASSISTANT)\]\s")
_MAX_MESSAGES = 400
_MAX_MESSAGE_CHARS = 20_000


def _digest_to_turns(digest: str) -> list[tuple[str, str]]:
    # The digest is redacted client-side, so persisting it puts no secrets into the message store.
    parts = _ROLE_MARKER.split(str(digest or ""))
    turns: list[tuple[str, str]] = []
    marks = iter(parts[1:])  # drop anything before the first role marker
    for role, text in zip(marks, marks):
        cleaned = str(text or "").strip()
        if cleaned:
            turns.append((role.lower(), cleaned[:_MAX_MESSAGE_CHARS]))
    return turns


async def _persist_session_messages(
    db: AsyncSession,
    *,
    session: Session,
    digest: str,
    model: str,
    provider: str,
    is_reingest: bool,
) -> int:
    if is_reingest:
        await db.execute(delete(Message).where(Message.session_id == session.id))
    turns = _digest_to_turns(digest)[:_MAX_MESSAGES]
    labelled_model = f"{provider}/{model}" if provider and model else (model or None)
    for role, text in turns:
        db.add(
            Message(
                id=str(uuid.uuid4()),
                session_id=session.id,
                role=role,
                content=text,
                model=labelled_model if role == "assistant" else None,
            )
        )
    await db.flush()
    return len(turns)


async def _link_work_item(
    db: AsyncSession, *, user: User, client_session_id: str, work_item_key: str
) -> dict[str, Any] | None:
    work_item_link: dict[str, Any] | None = None
    if work_item_key and client_session_id:
        # Session names its task: the digest becomes handover context in
        # work_item_context. Best effort - a wrong key must not lose usage.
        try:
            from .secure_work.platform_item_sessions import link_session_to_work_item

            work_item = (
                await db.execute(select(WorkItem).where(WorkItem.source_key == work_item_key).limit(1))
            ).scalar_one_or_none()
            if work_item is None:
                work_item_link = {"error": f"work item not found: {work_item_key}"}
            else:
                work_item_link = await link_session_to_work_item(
                    db, item=work_item, client_session_id=client_session_id, current_user=user
                )
        except Exception as exc:  # noqa: BLE001
            work_item_link = {"error": error_text("work_item_link_failed", exc)}
    return work_item_link
