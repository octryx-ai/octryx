"""MASH platform service — registration and lifecycle management."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ....time_utils import utc_now
from ..models import MashPlatform, MashPlatformCredential, MashPlatformQuota
from ..services.auth_service import generate_client_credentials, hash_client_secret, validate_scopes


async def register_platform(
    db: AsyncSession,
    *,
    name: str,
    description: str | None = None,
    platform_type: str = "octryx",
    metadata: dict[str, Any] | None = None,
    requested_scopes: list[str] | None = None,
) -> dict[str, Any]:
    existing = await db.execute(
        select(MashPlatform).where(MashPlatform.name == name)
    )
    if existing.scalar_one_or_none():
        raise ValueError(f"Platform '{name}' already exists")

    platform = MashPlatform(
        name=name,
        description=description,
        platform_type=platform_type,
        metadata_json=metadata,
        status="registered",
    )
    db.add(platform)
    await db.flush()

    client_id, client_secret = generate_client_credentials()
    scopes = validate_scopes(requested_scopes or []) or [
        "policies:read",
        "audit:write",
        "stats:write",
    ]

    cred = MashPlatformCredential(
        platform_id=platform.id,
        client_id=client_id,
        client_secret_hash=hash_client_secret(client_secret),
        scopes=scopes,
    )
    db.add(cred)

    quota = MashPlatformQuota(platform_id=platform.id)
    db.add(quota)

    await db.commit()

    return {
        "platform_id": platform.id,
        "name": platform.name,
        "client_id": client_id,
        "client_secret": client_secret,
        "scopes": scopes,
        "status": platform.status,
    }


async def get_platform_info(db: AsyncSession, *, platform_id: str) -> dict[str, Any] | None:
    platform = await db.get(MashPlatform, platform_id)
    if not platform:
        return None
    return {
        "platform_id": platform.id,
        "name": platform.name,
        "description": platform.description,
        "platform_type": platform.platform_type,
        "status": platform.status,
        "tags": platform.tags,
        "metadata": platform.metadata_json,
        "capabilities": platform.capabilities_json,
        "registered_at": platform.registered_at.isoformat() if platform.registered_at else None,
        "last_seen_at": platform.last_seen_at.isoformat() if platform.last_seen_at else None,
    }


async def heartbeat(
    db: AsyncSession,
    *,
    platform_id: str,
    capabilities: dict[str, Any] | None = None,
) -> dict[str, Any]:
    platform = await db.get(MashPlatform, platform_id)
    if not platform:
        raise ValueError("Platform not found")

    platform.last_seen_at = utc_now()
    platform.status = "online"
    if capabilities:
        platform.capabilities_json = capabilities

    await db.commit()
    return {"status": "ok", "platform_status": platform.status}


async def list_platforms(db: AsyncSession) -> list[dict[str, Any]]:
    result = await db.execute(select(MashPlatform).order_by(MashPlatform.name))
    platforms = result.scalars().all()
    return [
        {
            "platform_id": p.id,
            "name": p.name,
            "platform_type": p.platform_type,
            "status": p.status,
            "tags": p.tags,
            "last_seen_at": p.last_seen_at.isoformat() if p.last_seen_at else None,
        }
        for p in platforms
    ]
