"""Guards on the public trigger before any alert is decided (automation review fixes)."""

from __future__ import annotations

import time
from collections import defaultdict, deque
from datetime import timedelta

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ...models.integration.webhook import Webhook, WebhookDeliveryKey, WebhookEvent
from ...time_utils import utc_now
from .signature import REJECT_STALE_TIMESTAMP, REJECT_TIMESTAMP_REQUIRED, TIMESTAMP_TOLERANCE_SECONDS

OUTCOME_REJECTED_SIGNATURE = "rejected_signature"
OUTCOME_REJECTED_REPLAY = "rejected_replay"
REJECTED_OUTCOMES = (OUTCOME_REJECTED_SIGNATURE, OUTCOME_REJECTED_REPLAY)
KEY_RETENTION = timedelta(hours=1)
MAX_CALLS_PER_MINUTE = 120

_REJECTION_WORDS = {
    REJECT_TIMESTAMP_REQUIRED: "Refused: the call had no signed timestamp. Nothing started.",
    REJECT_STALE_TIMESTAMP: "Refused: the signed timestamp was more than 5 minutes off. Nothing started.",
    OUTCOME_REJECTED_REPLAY: "Refused: this exact call was already accepted (replay). Nothing started.",
}
_BAD_SIGNATURE_WORDS = "The signature didn't match. Nothing started."

_calls: dict[tuple[str, str], deque[float]] = defaultdict(deque)


def allow_call(webhook_id: str, client: str, now: float | None = None) -> bool:
    current = now if now is not None else time.monotonic()
    window = _calls[(webhook_id, client)]
    while window and current - window[0] > 60:
        window.popleft()
    if len(window) >= MAX_CALLS_PER_MINUTE:
        return False
    window.append(current)
    return True


async def record_rejection(db: AsyncSession, webhook: Webhook, *, outcome: str, reason: str | None) -> None:
    words = _REJECTION_WORDS.get(reason or outcome, _BAD_SIGNATURE_WORDS)
    since = utc_now() - timedelta(minutes=1)
    recent = (
        await db.execute(
            select(WebhookEvent)
            .where(WebhookEvent.webhook_id == webhook.id, WebhookEvent.outcome == outcome,
                   WebhookEvent.received_at >= since)
            .order_by(WebhookEvent.received_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if recent is not None:
        count = int((recent.raw_payload or {}).get("count") or 1) + 1
        recent.raw_payload = {"count": count, "reason": reason or outcome}
        recent.parsed_message = f"{words} ({count} calls in this minute)"
    else:
        db.add(WebhookEvent(webhook_id=webhook.id, status="skipped", outcome=outcome, parsed_message=words,
                            raw_payload={"count": 1, "reason": reason or outcome}, processed_at=utc_now()))
    await db.commit()


async def claim_delivery_key(db: AsyncSession, webhook_id: str, key: str) -> bool:
    now = utc_now()
    window_start = now - timedelta(seconds=TIMESTAMP_TOLERANCE_SECONDS)
    await db.execute(delete(WebhookDeliveryKey).where(WebhookDeliveryKey.seen_at < now - KEY_RETENTION))
    existing = (
        await db.execute(
            select(WebhookDeliveryKey).where(WebhookDeliveryKey.webhook_id == webhook_id,
                                             WebhookDeliveryKey.delivery_key == key)
        )
    ).scalar_one_or_none()
    if existing is not None:
        if existing.seen_at >= window_start:
            return False
        existing.seen_at = now
        await db.flush()
        return True
    try:
        async with db.begin_nested():
            db.add(WebhookDeliveryKey(webhook_id=webhook_id, delivery_key=key[:128], seen_at=now))
    except IntegrityError:
        return False  # a concurrent call claimed it first
    return True


async def release_delivery_key(db: AsyncSession, webhook_id: str, key: str) -> None:
    await db.execute(
        delete(WebhookDeliveryKey).where(WebhookDeliveryKey.webhook_id == webhook_id,
                                         WebhookDeliveryKey.delivery_key == key)
    )
    await db.commit()


__all__ = [
    "MAX_CALLS_PER_MINUTE",
    "OUTCOME_REJECTED_REPLAY",
    "OUTCOME_REJECTED_SIGNATURE",
    "REJECTED_OUTCOMES",
    "allow_call",
    "claim_delivery_key",
    "record_rejection",
    "release_delivery_key",
]
