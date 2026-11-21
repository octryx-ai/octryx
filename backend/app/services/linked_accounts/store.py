"""Read, save and remove a user's linked accounts; every change is an ``audit_log`` row.

Who may change whose accounts is the route's decision (``api/routes/linked_accounts``: the user themself or a
platform admin); the audit row names the actor and the user. A changed identifier resets the verification.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import AuditLog, UserLinkedAccount
from ...time_utils import utc_now
from .contract import ACCOUNT_ID, PLATFORMS, STATUS_UNVERIFIED, STATUS_VERIFIED, normalized_identifier, platform

RESOURCE = "user_linked_account"


def identifier_of(row: UserLinkedAccount | None) -> str:
    if row is None:
        return ""
    value = row.account_id if PLATFORMS[row.platform].identifier == ACCOUNT_ID else row.username
    return str(value or "").strip()


def _iso(value: Any) -> str | None:
    return value.isoformat() if value is not None else None


def serialize_account(row: UserLinkedAccount) -> dict[str, Any]:
    spec = PLATFORMS[row.platform]
    verification = dict(row.verification_json or {})
    return {
        "platform": row.platform, "label": spec.label, "identifier_kind": spec.identifier,
        "identifier": identifier_of(row), "display_name": row.display_name,
        "verification_status": row.verification_status, "verified_at": _iso(row.verified_at),
        "verification": {key: verification[key] for key in ("detail", "via", "project_id") if key in verification},
        "source": row.source, "updated_at": _iso(row.updated_at),
    }


def platform_catalog() -> list[dict[str, str]]:
    return [{"platform": spec.key, "label": spec.label, "identifier_kind": spec.identifier,
             "description": spec.description} for spec in PLATFORMS.values()]


async def account_rows(db: AsyncSession, user_id: str) -> list[UserLinkedAccount]:
    rows = (await db.execute(select(UserLinkedAccount).where(UserLinkedAccount.user_id == user_id))).scalars().all()
    order = list(PLATFORMS)
    return sorted((row for row in rows if row.platform in PLATFORMS), key=lambda row: order.index(row.platform))


async def account_row(db: AsyncSession, user_id: str, platform_key: str) -> UserLinkedAccount | None:
    return (await db.execute(select(UserLinkedAccount).where(
        UserLinkedAccount.user_id == user_id, UserLinkedAccount.platform == platform_key,
    ))).scalars().first()


def audit(db: AsyncSession, *, actor_id: str, user_id: str, action: str, row: UserLinkedAccount,
          details: dict[str, Any] | None = None) -> None:
    db.add(AuditLog(user_id=actor_id, action=f"linked_account.{action}", resource_type=RESOURCE, resource_id=row.id,
                    details={"user_id": user_id, "platform": row.platform, "identifier": identifier_of(row),
                             "by_admin": actor_id != user_id, **(details or {})}))


async def save_account(
    db: AsyncSession, *, user_id: str, platform_key: str, identifier: str, display_name: str | None, actor_id: str,
    verified: dict[str, Any] | None = None,
) -> UserLinkedAccount:
    """Create or change the user's account on the platform; ``verified`` marks it verified (a lookup found it)."""
    spec = platform(platform_key)
    value = normalized_identifier(spec, identifier)
    row = await account_row(db, user_id, spec.key)
    previous = identifier_of(row)
    if row is None:
        row = UserLinkedAccount(user_id=user_id, platform=spec.key, created_by=actor_id,
                                source="self" if actor_id == user_id else "admin", verification_json={})
        db.add(row)
    changed = previous != value
    if spec.identifier == ACCOUNT_ID:
        row.account_id, row.username = value, None
    else:
        row.username, row.account_id = value, None
    name = str(display_name or "").strip()[:255]
    if name or changed:
        row.display_name = name or None
    if changed:
        row.verification_status, row.verified_at, row.verification_json = STATUS_UNVERIFIED, None, {}
    row.updated_by = actor_id
    if not previous:
        row.source = "self" if actor_id == user_id else "admin"
    await db.flush()
    if changed or name:
        audit(db, actor_id=actor_id, user_id=user_id, action="saved", row=row,
              details={"previous_identifier": previous or None})
    if verified is not None:
        mark_verification(db, row, status=verified["status"], detail=verified.get("detail", ""),
                          via=verified.get("via", ""), project_id=verified.get("project_id"), actor_id=actor_id,
                          display_name=verified.get("display_name"))
    return row


def mark_verification(
    db: AsyncSession, row: UserLinkedAccount, *, status: str, detail: str, via: str, project_id: str | None,
    actor_id: str, display_name: str | None = None,
) -> None:
    row.verification_status = status
    row.verified_at = utc_now() if status == STATUS_VERIFIED else None
    row.verification_json = {"detail": detail, "via": via, "project_id": project_id}
    if display_name and status == STATUS_VERIFIED:
        row.display_name = str(display_name)[:255]
    row.updated_by = actor_id
    audit(db, actor_id=actor_id, user_id=row.user_id, action=f"verification_{status}", row=row,
          details={"via": via, "project_id": project_id, "detail": detail})


async def remove_account(db: AsyncSession, *, user_id: str, platform_key: str, actor_id: str) -> bool:
    spec = platform(platform_key)
    row = await account_row(db, user_id, spec.key)
    if row is None:
        return False
    audit(db, actor_id=actor_id, user_id=user_id, action="removed", row=row)
    await db.delete(row)
    await db.flush()
    return True


__all__ = [
    "account_row",
    "account_rows",
    "identifier_of",
    "mark_verification",
    "platform_catalog",
    "remove_account",
    "save_account",
    "serialize_account",
]
