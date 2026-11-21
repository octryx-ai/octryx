"""The Cedar principal for a user (platform roles and identity groups as parents), cached briefly.

Roles are the platform roles (``user_roles``); ``platform_admin`` is the ``admin`` role, the same rule as
``access_control._user_is_admin``. Groups are the active identity groups. A lookup failure yields the user
without roles or groups: the principal only narrows (custom ``forbid`` policies), it never grants.

A live enforcement point loads the principal with :func:`load_principal_isolated`: the role and group queries
run in their own session, so a failing statement (which aborts a PostgreSQL transaction) never reaches the
caller's transaction.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Mapping
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import IdentityGroup, Role, UserGroup, UserRole
from .engine import EntityRef
from .entities import principal_entities

logger = logging.getLogger(__name__)

CACHE_SECONDS = 60.0
CACHE_SIZE = 1024
ADMIN_ROLE = "admin"

_CACHE: dict[str, tuple[float, tuple[str, ...], tuple[str, ...]]] = {}


async def user_roles_and_groups(db: AsyncSession, user_id: str) -> tuple[tuple[str, ...], tuple[str, ...]]:
    cached = _CACHE.get(user_id)
    if cached is not None and time.monotonic() - cached[0] < CACHE_SECONDS:
        return cached[1], cached[2]
    roles = (
        await db.execute(
            select(Role.name).join(UserRole, UserRole.role_id == Role.id).where(UserRole.user_id == user_id)
        )
    ).scalars()
    groups = (
        await db.execute(
            select(IdentityGroup.name)
            .join(UserGroup, UserGroup.group_id == IdentityGroup.id)
            .where(UserGroup.user_id == user_id, IdentityGroup.is_active.is_(True))
        )
    ).scalars()
    result = (tuple(sorted({str(name).strip() for name in roles if name})),
              tuple(sorted({str(name).strip() for name in groups if name})))
    if len(_CACHE) >= CACHE_SIZE:
        _CACHE.clear()
    _CACHE[user_id] = (time.monotonic(), *result)
    return result


async def load_principal(
    db: AsyncSession | None, user_id: str | None, *, session_id: str | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> tuple[EntityRef, list[dict[str, Any]]]:
    roles: tuple[str, ...] = ()
    groups: tuple[str, ...] = ()
    if user_id and db is not None:
        try:
            roles, groups = await user_roles_and_groups(db, user_id)
        except Exception:  # noqa: BLE001 - a principal without roles only narrows less, it never grants
            logger.warning("policy_engine_principal_lookup_failed", exc_info=True)
    meta = metadata if isinstance(metadata, Mapping) else {}
    return principal_entities(
        user_id,
        roles=roles,
        groups=groups,
        platform_admin=ADMIN_ROLE in {role.lower() for role in roles},
        session_id=session_id,
        profile=str(meta.get("profile") or "governed"),
        client=str(meta.get("client") or ""),
    )


async def load_principal_isolated(
    user_id: str | None, *, session_id: str | None = None, metadata: Mapping[str, Any] | None = None
) -> tuple[EntityRef, list[dict[str, Any]]]:
    """:func:`load_principal` in its own database session; never raises (the user without roles or groups)."""
    from ...db import core as db_core

    try:
        async with db_core.async_session_factory() as session:
            return await load_principal(session, user_id, session_id=session_id, metadata=metadata)
    except Exception:  # noqa: BLE001 - see load_principal: a principal without roles only narrows less
        logger.warning("policy_engine_principal_session_failed", exc_info=True)
    return await load_principal(None, user_id, session_id=session_id, metadata=metadata)


async def load_session_metadata_isolated(session_id: str) -> Mapping[str, Any] | None:
    """The session's metadata (profile, client) in its own database session; ``None`` when it cannot be read."""
    from ...db import core as db_core
    from ...models import Session

    try:
        async with db_core.async_session_factory() as session:
            row = await session.get(Session, session_id)
            return row.metadata_ if row is not None and isinstance(row.metadata_, Mapping) else None
    except Exception:  # noqa: BLE001 - the profile defaults to governed; it never grants
        logger.warning("policy_engine_session_metadata_failed", exc_info=True)
    return None


def clear_principal_cache() -> None:
    _CACHE.clear()


__all__ = [
    "clear_principal_cache",
    "load_principal",
    "load_principal_isolated",
    "load_session_metadata_isolated",
    "user_roles_and_groups",
]
