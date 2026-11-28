"""Notifications on the paired phone (Octryx Mobile)."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...config import get_settings
from ...models import MobileDevice, MobilePushSubscription, User
from ...time_utils import utc_now
from .devices import phone_refusal
from .webpush import GONE, SENT, Subscription, endpoint_allowed, load_vapid_key, public_key_b64, send, unb64url

logger = logging.getLogger(__name__)

SWEEP_SECONDS = 20.0
MAX_PER_SWEEP = 3
MAX_FAILURES = 10
MAX_REMEMBERED = 500
GROUPS = ("needs_you", "problem", "done")
DEFAULT_RULES = {"needs_you": True, "problem": True, "done": False}
THRESHOLD_KINDS = frozenset({"budget", "allowance"})
TITLES = {"needs_you": "Needs you", "problem": "Problem", "done": "Done"}
REASON_NOT_CONFIGURED = "mobile_push_not_configured"
REASON_SUBSCRIPTION_INVALID = "mobile_push_subscription_invalid"


def group_of(entry: dict[str, Any]) -> str | None:
    if entry.get("severity") == "action" or entry.get("kind") in THRESHOLD_KINDS:
        return "needs_you"
    if entry.get("severity") == "warning":
        return "problem"
    if entry.get("severity") == "info":
        return "done"
    return None


def normalize_rules(value: Any) -> dict[str, bool]:
    rules = dict(DEFAULT_RULES)
    if isinstance(value, dict):
        rules.update({group: value[group] for group in GROUPS if type(value.get(group)) is bool})
    return rules


def vapid() -> tuple[Any, str] | None:
    settings = get_settings()
    key = load_vapid_key(getattr(settings, "mobile_vapid_private_key", None))
    if key is None:
        return None
    subject = str(getattr(settings, "mobile_vapid_subject", "") or "").strip()
    origin = str(settings.platform_public_origin or "").strip()
    return key, subject or (origin if origin.startswith("https://") else "mailto:octryx@octryx.invalid")


def push_state(subscription: MobilePushSubscription | None) -> dict[str, Any]:
    configured = vapid()
    return {
        "configured": configured is not None,
        "public_key": public_key_b64(configured[0]) if configured else None,
        "subscribed": subscription is not None,
        "rules": normalize_rules(subscription.rules if subscription else None),
    }


async def phone_subscription(db: AsyncSession, device_id: str) -> MobilePushSubscription | None:
    return (await db.execute(select(MobilePushSubscription).where(
        MobilePushSubscription.mobile_device_id == device_id))).scalar_one_or_none()


async def subscribe(db: AsyncSession, device: MobileDevice, body: Any) -> MobilePushSubscription | str:
    if vapid() is None:
        return REASON_NOT_CONFIGURED
    raw = body.get("subscription") if isinstance(body, dict) else None
    keys = raw.get("keys") if isinstance(raw, dict) else None
    endpoint = raw.get("endpoint") if isinstance(raw, dict) else None
    p256dh = keys.get("p256dh") if isinstance(keys, dict) else None
    auth = keys.get("auth") if isinstance(keys, dict) else None
    if not endpoint_allowed(endpoint) or not isinstance(p256dh, str) or not isinstance(auth, str):
        return REASON_SUBSCRIPTION_INVALID
    try:
        if len(unb64url(p256dh)) != 65 or len(unb64url(auth)) < 16 or len(p256dh) > 200 or len(auth) > 100:
            return REASON_SUBSCRIPTION_INVALID
    except ValueError:
        return REASON_SUBSCRIPTION_INVALID
    row = await phone_subscription(db, device.id)
    if row is None:
        row = MobilePushSubscription(mobile_device_id=device.id, owner_user_id=device.owner_user_id, notified=None)
        db.add(row)
    elif row.endpoint != endpoint:
        row.notified = None  # a new subscription starts from what is there now
    row.endpoint, row.p256dh, row.auth, row.failures = endpoint, p256dh, auth, 0
    row.rules = normalize_rules(body.get("rules") if isinstance(body, dict) else None)
    await db.flush()
    return row


async def set_rules(db: AsyncSession, device: MobileDevice, rules: Any) -> MobilePushSubscription | None:
    row = await phone_subscription(db, device.id)
    if row is not None:  # a partial change keeps the other groups as they are
        row.rules = normalize_rules({**normalize_rules(row.rules), **(rules if isinstance(rules, dict) else {})})
        await db.flush()
    return row


async def unsubscribe(db: AsyncSession, device: MobileDevice) -> None:
    await db.execute(delete(MobilePushSubscription).where(MobilePushSubscription.mobile_device_id == device.id))
    await db.flush()


def messages_for(new: list[dict[str, Any]], badge: int) -> list[dict[str, Any]]:
    shown = new[:MAX_PER_SWEEP]
    out = []
    for entry in shown:
        group = group_of(entry) or "needs_you"
        workspace = (entry.get("workspace") or {}).get("name") if isinstance(entry.get("workspace"), dict) else ""
        body = str(entry.get("title") or "")[:160] + (f" · {workspace}" if workspace else "")
        out.append({"title": TITLES[group], "body": body, "tag": str(entry.get("key") or "")[:120],
                    "url": f"/m/#item={entry.get('key') or ''}", "badge": badge})
    if len(new) > MAX_PER_SWEEP:
        out.append({"title": "Octryx", "body": f"and {len(new) - MAX_PER_SWEEP} more", "tag": "octryx-more",
                    "url": "/m/", "badge": badge})
    return out


Sender = Any  # (http, Subscription, message, key=, subject=) -> str


async def sweep_subscription(db: AsyncSession, row: MobilePushSubscription, *, http: httpx.AsyncClient,
                             sender: Sender = send) -> int:
    configured = vapid()
    device = await db.get(MobileDevice, row.mobile_device_id)
    if configured is None:
        return 0
    if await phone_refusal(db, device):  # revoked or expired: the subscription goes with it
        await db.delete(row)
        await db.flush()
        return 0
    user = await db.get(User, row.owner_user_id)
    from ..attention.service import attention  # noqa: PLC0415 - the queue builds on many services

    queue = await attention(db, user)
    entries = [entry for entry in queue.get("items") or [] if isinstance(entry, dict) and entry.get("key")]
    present = [str(entry["key"]) for entry in entries]
    if row.notified is None:
        row.notified = present  # the first look only takes note
        await db.flush()
        return 0
    seen = set(row.notified or [])
    rules = normalize_rules(row.rules)
    quiet = bool((queue.get("quiet") or {}).get("active"))
    new = [entry for entry in entries if str(entry["key"]) not in seen and rules.get(group_of(entry) or "", False)]
    # Remember what was notified even when it leaves the queue for a while (a run paused and resumed many
    # times would push the same entry again each time); the newest MAX_REMEMBERED keys are kept.
    row.notified = (present + [key for key in row.notified or [] if key not in set(present)])[:MAX_REMEMBERED]
    sent = 0
    if new and not quiet:
        badge = sum(1 for entry in entries if group_of(entry) == "needs_you")
        subscription = Subscription(endpoint=row.endpoint, p256dh=row.p256dh, auth=row.auth)
        key, subject = configured
        for message in messages_for(new, badge):
            urgency = "high" if message["title"] == TITLES["needs_you"] else "normal"
            outcome = await sender(http, subscription, message, key=key, subject=subject, urgency=urgency)
            if outcome == GONE:
                await db.delete(row)
                await db.flush()
                return sent
            if outcome == SENT:
                sent += 1
        row.failures = 0 if sent else (row.failures or 0) + 1
        row.last_sent_at = utc_now() if sent else row.last_sent_at
        if (row.failures or 0) >= MAX_FAILURES:
            await db.delete(row)
    await db.flush()
    return sent


async def sweep_once(session_factory, *, http: httpx.AsyncClient, sender: Sender = send) -> int:
    if vapid() is None:
        return 0
    async with session_factory() as db:
        ids = list((await db.execute(select(MobilePushSubscription.id))).scalars())
    total = 0
    for subscription_id in ids:
        try:
            async with session_factory() as db:
                query = select(MobilePushSubscription).where(MobilePushSubscription.id == subscription_id)
                row = (await db.execute(query.with_for_update(skip_locked=True))).scalar_one_or_none()
                if row is None:
                    continue
                total += await sweep_subscription(db, row, http=http, sender=sender)
                await db.commit()
        except Exception as exc:  # noqa: BLE001 - one phone's problem never stops the sweep
            logger.warning("mobile_push_sweep_failed", extra={"error_type": type(exc).__name__})
    return total


class MobilePushSweeper:
    def __init__(self, session_factory, *, seconds: float = SWEEP_SECONDS) -> None:
        self._session_factory = session_factory
        self._seconds = seconds
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._run(), name="mobile-push-sweeper")

    async def stop(self) -> None:
        task, self._task = self._task, None
        if task is not None:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    async def _run(self) -> None:
        async with httpx.AsyncClient() as http:
            while True:
                await asyncio.sleep(self._seconds)
                try:
                    await sweep_once(self._session_factory, http=http)
                except asyncio.CancelledError:
                    raise
                except Exception as exc:  # noqa: BLE001 - the next sweep tries again
                    logger.warning("mobile_push_sweep_failed", extra={"error_type": type(exc).__name__})


__all__ = ["DEFAULT_RULES", "MobilePushSweeper", "group_of", "messages_for", "normalize_rules", "phone_subscription",
           "push_state", "set_rules", "subscribe", "sweep_once", "sweep_subscription", "unsubscribe", "vapid"]
