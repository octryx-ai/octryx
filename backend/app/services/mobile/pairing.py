"""Pairing a phone with the QR code from the Mac.

1. ``create_pairing``: the user's own octryx-claude login on the Mac asks for a pairing. The one-time code goes
   into the QR code as the URL fragment (``/m/pair#c=…``), so it never reaches a server log.
2. ``scan``: the phone (Safari after the camera, or the app) redeems the code once. It gets a scan secret (only
   this phone can follow the pairing) and a two-digit number; the Mac shows the same number.
3. ``confirm``: the person confirms the number in their signed-in browser on the Mac (the platform's web session,
   same origin), never with the Mac's gateway token: a token that leaked to a tool or an agent can start a
   pairing but never complete one. A code someone else photographed is useless without it.
4. ``phone_status``: the scanning phone learns the decision; after a confirmation it receives the one-time claim,
   exactly once.
5. ``claim``: the Home Screen app redeems the claim on its first start and becomes a mobile device.

Secrets are stored as SHA-256 hashes and compared in constant time; every step is audited.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import AuditLog, MobileDevice, MobilePairing, User
from ...models.security.mobile import (
    PAIRING_CLAIMED,
    PAIRING_CONFIRMED,
    PAIRING_DENIED,
    PAIRING_PENDING,
    PAIRING_SCANNED,
    mobile_device_pk,
)
from ...time_utils import ensure_utc, utc_now, utc_now_aware
from .contract import (
    AUDIT_DEVICE_PAIRED,
    AUDIT_PAIRING_CONFIRMED,
    AUDIT_PAIRING_CREATED,
    AUDIT_PAIRING_DENIED,
    AUDIT_PAIRING_SCANNED,
    CLAIM_ALPHABET,
    CLAIM_LENGTH,
    CLAIM_TTL,
    CODE_BYTES,
    CODE_TTL,
    CONFIRM_PATH,
    CONFIRM_TTL,
    PAIR_PATH,
    PAIRING_LIMIT,
    PAIRING_LIMIT_WINDOW,
    REASON_CLAIM_INVALID,
    REASON_PAIRING_DENIED,
    REASON_PAIRING_EXPIRED,
    REASON_PAIRING_NOT_FOUND,
    REASON_PAIRING_NOT_SCANNED,
    REASON_PAIRING_USED,
    REASON_TOO_MANY,
    SECRET_BYTES,
)

MAX_LABEL_CHARS = 80


def secret_hash(secret: str) -> str:
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


def _matches(secret: str, stored: str | None) -> bool:
    return bool(stored) and hmac.compare_digest(secret_hash(secret), str(stored))


def new_claim_code() -> str:
    return "".join(secrets.choice(CLAIM_ALPHABET) for _ in range(CLAIM_LENGTH))


def normalize_claim_code(text: object) -> str:
    """``k7q4-xm9p`` → ``K7Q4XM9P``; O/I/L read as 0/1/1 (Crockford); anything else is ``""``."""
    raw = str(text or "").upper().replace("-", "").replace(" ", "")
    raw = raw.translate(str.maketrans({"O": "0", "I": "1", "L": "1"}))
    return raw if len(raw) == CLAIM_LENGTH and all(char in CLAIM_ALPHABET for char in raw) else ""


def confirm_url(base_url: str, pairing_id: str) -> str:
    """The page in the person's browser where they confirm the phone (the pairing id is no secret)."""
    return f"{base_url.rstrip('/')}{CONFIRM_PATH}?p={pairing_id}"


def pair_url(base_url: str, code: str) -> str:
    return f"{base_url.rstrip('/')}{PAIR_PATH}#c={code}"


def phone_label(user_agent: str) -> str:
    """A short, readable name for the phone from its user agent ("iPhone", "iPad", "Android phone", …)."""
    agent = str(user_agent or "")
    for needle, label in (("iPhone", "iPhone"), ("iPad", "iPad"), ("Android", "Android phone"), ("Mac", "Mac")):
        if needle in agent:
            return label
    return "Phone"


def _expired(moment: Any) -> bool:
    return moment is None or ensure_utc(moment) <= utc_now_aware()


def _audit(db: AsyncSession, *, user_id: str, action: str, pairing: MobilePairing, details: dict | None = None) -> None:
    db.add(AuditLog(user_id=user_id, action=action, resource_type="mobile_pairing", resource_id=pairing.id,
                    details=details or {}))


async def _advance(db: AsyncSession, pairing: MobilePairing, *, expected: str, claim_unset: bool = False,
                   **values: Any) -> bool:
    """Move the pairing on only if it is still in ``expected`` (and, for the claim, none was handed out yet): one
    conditional UPDATE, so two concurrent scans, confirmations or claims never both succeed."""
    statement = update(MobilePairing).where(MobilePairing.id == pairing.id, MobilePairing.state == expected)
    if claim_unset:
        statement = statement.where(MobilePairing.claim_hash.is_(None))
    result = await db.execute(statement.values(**values).execution_options(synchronize_session=False))
    if result.rowcount != 1:
        return False
    await db.refresh(pairing)
    return True


@dataclass(frozen=True, slots=True)
class Scan:
    pairing: MobilePairing
    scan_secret: str


async def create_pairing(db: AsyncSession, *, user_id: str, grant_id: str) -> tuple[MobilePairing, str] | str:
    """A new pairing of ``user_id`` from the octryx-claude login ``grant_id`` and its one-time code (returned once),
    or ``mobile_pairing_limit`` after too many in a short time. Flushes."""
    since = utc_now() - PAIRING_LIMIT_WINDOW
    recent = (await db.execute(select(func.count()).select_from(MobilePairing).where(
        MobilePairing.user_id == user_id, MobilePairing.created_at >= since))).scalar_one()
    if recent >= PAIRING_LIMIT:
        return REASON_TOO_MANY
    code = secrets.token_urlsafe(CODE_BYTES)
    pairing = MobilePairing(user_id=user_id, grant_id=grant_id, code_hash=secret_hash(code), state=PAIRING_PENDING,
                            expires_at=utc_now() + CODE_TTL)
    db.add(pairing)
    await db.flush()
    _audit(db, user_id=user_id, action=AUDIT_PAIRING_CREATED, pairing=pairing)
    await db.flush()
    return pairing, code


async def owned_pairing(db: AsyncSession, *, pairing_id: str, user_id: str) -> MobilePairing | str:
    pairing = await db.get(MobilePairing, pairing_id) if pairing_id else None
    if pairing is None or pairing.user_id != user_id:
        return REASON_PAIRING_NOT_FOUND
    return pairing


async def scan(db: AsyncSession, *, code: str, user_agent: str) -> Scan | str:
    """The phone redeems the code once; returns the scan secret (once) or a fixed reason. Flushes."""
    if not isinstance(code, str) or not 10 <= len(code) <= 64:
        return REASON_PAIRING_NOT_FOUND
    pairing = (
        await db.execute(select(MobilePairing).where(MobilePairing.code_hash == secret_hash(code)))
    ).scalar_one_or_none()
    if pairing is None:
        return REASON_PAIRING_NOT_FOUND
    if pairing.state != PAIRING_PENDING:
        return REASON_PAIRING_USED
    if _expired(pairing.expires_at):
        return REASON_PAIRING_EXPIRED
    scan_secret = secrets.token_urlsafe(SECRET_BYTES)
    if not await _advance(db, pairing, expected=PAIRING_PENDING, state=PAIRING_SCANNED,
                          scan_secret_hash=secret_hash(scan_secret), match_number=f"{10 + secrets.randbelow(90)}",
                          phone_label=phone_label(user_agent)[:MAX_LABEL_CHARS], scanned_at=utc_now(),
                          expires_at=utc_now() + CONFIRM_TTL):
        return REASON_PAIRING_USED  # another phone scanned it at the same moment
    _audit(db, user_id=pairing.user_id, action=AUDIT_PAIRING_SCANNED, pairing=pairing,
           details={"phone": pairing.phone_label})
    await db.flush()
    return Scan(pairing=pairing, scan_secret=scan_secret)


def mac_view(pairing: MobilePairing) -> dict[str, Any]:
    """What the Mac shows while it waits: the state, and after a scan the number and the phone."""
    state = pairing.state
    if state in (PAIRING_PENDING, PAIRING_SCANNED) and _expired(pairing.expires_at):
        state = "expired"
    view: dict[str, Any] = {"pairing_id": pairing.id, "state": state,
                            "expires_at": ensure_utc(pairing.expires_at).isoformat()}
    if pairing.state != PAIRING_PENDING:
        view["match_number"] = pairing.match_number
        view["phone"] = pairing.phone_label
    return view


async def confirm(db: AsyncSession, *, pairing: MobilePairing, user_id: str, approve: bool) -> str:
    """The Mac's decision on a scanned pairing; ``""`` or a fixed reason. Flushes."""
    if pairing.state == PAIRING_PENDING:
        return REASON_PAIRING_NOT_SCANNED
    if pairing.state != PAIRING_SCANNED:
        return REASON_PAIRING_USED
    if _expired(pairing.expires_at):
        return REASON_PAIRING_EXPIRED
    values = ({"state": PAIRING_CONFIRMED, "confirmed_at": utc_now(), "claim_expires_at": utc_now() + CLAIM_TTL}
              if approve else {"state": PAIRING_DENIED})
    if not await _advance(db, pairing, expected=PAIRING_SCANNED, **values):
        return REASON_PAIRING_USED
    _audit(db, user_id=user_id, action=AUDIT_PAIRING_CONFIRMED if approve else AUDIT_PAIRING_DENIED,
           pairing=pairing, details={"phone": pairing.phone_label})
    await db.flush()
    return ""


async def phone_status(db: AsyncSession, *, pairing_id: str, scan_secret: str) -> dict[str, Any] | str:
    """The scanning phone's view; the claim is handed out once, right after the confirmation. Flushes."""
    pairing = await db.get(MobilePairing, pairing_id) if pairing_id else None
    if pairing is None or not isinstance(scan_secret, str) or not _matches(scan_secret, pairing.scan_secret_hash):
        return REASON_PAIRING_NOT_FOUND
    if pairing.state == PAIRING_DENIED:
        return REASON_PAIRING_DENIED
    if pairing.state == PAIRING_SCANNED:
        if _expired(pairing.expires_at):
            return REASON_PAIRING_EXPIRED
        return {"state": "waiting", "match_number": pairing.match_number}
    if pairing.state == PAIRING_CONFIRMED and pairing.claim_hash is None and not _expired(pairing.claim_expires_at):
        claim = new_claim_code()
        if not await _advance(db, pairing, expected=PAIRING_CONFIRMED, claim_unset=True, claim_hash=secret_hash(claim)):
            return REASON_PAIRING_USED
        return {"state": "confirmed", "claim": f"{claim[:4]}-{claim[4:]}",
                "claim_expires_at": ensure_utc(pairing.claim_expires_at).isoformat()}
    return REASON_PAIRING_USED


async def claim(db: AsyncSession, *, claim_token: str, name: str = "") -> tuple[MobileDevice, str] | str:
    """The Home Screen app's first start: a new mobile device and its secret (returned once). Flushes."""
    code = normalize_claim_code(claim_token)
    if not code:
        return REASON_CLAIM_INVALID
    pairing = (
        await db.execute(select(MobilePairing).where(MobilePairing.claim_hash == secret_hash(code)))
    ).scalar_one_or_none()
    if pairing is None or pairing.state != PAIRING_CONFIRMED or _expired(pairing.claim_expires_at):
        return REASON_CLAIM_INVALID
    owner = await db.get(User, pairing.user_id)
    if owner is None or not owner.is_active:
        return REASON_CLAIM_INVALID
    secret = secrets.token_urlsafe(SECRET_BYTES)
    label = (str(name or "").strip() or pairing.phone_label or "Phone")[:MAX_LABEL_CHARS]
    device = MobileDevice(id=mobile_device_pk(), owner_user_id=pairing.user_id, grant_id=pairing.grant_id,
                          name=label, secret_hash=secret_hash(secret), last_seen_at=utc_now())
    # The single-use step first: of two concurrent claims exactly one moves the pairing on and gets a device.
    if not await _advance(db, pairing, expected=PAIRING_CONFIRMED, state=PAIRING_CLAIMED, claimed_at=utc_now(),
                          mobile_device_id=device.id):
        return REASON_CLAIM_INVALID
    db.add(device)
    await db.flush()
    db.add(AuditLog(user_id=pairing.user_id, action=AUDIT_DEVICE_PAIRED, resource_type="mobile_device",
                    resource_id=device.id, details={"pairing_id": pairing.id, "name": label}))
    await db.flush()
    return device, secret


__all__ = [
    "Scan",
    "claim",
    "confirm",
    "confirm_url",
    "create_pairing",
    "mac_view",
    "normalize_claim_code",
    "owned_pairing",
    "pair_url",
    "phone_label",
    "phone_status",
    "scan",
    "secret_hash",
]
