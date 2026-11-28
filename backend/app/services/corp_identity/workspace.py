"""Which Corporate Identity a Workspace uses, and which of its values the Spec Studio may not change."""

from __future__ import annotations

import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..system_config import get_system_config_value
from .registry import CORP_IDENTITY_DEFAULT_PROFILE_KEY, load_registry, save_registry

WORKSPACE_KEY = "corp_identity_profile_id"
LOCKS_KEY = "studio_locks"
SOURCE_WORKSPACE = "workspace"
SOURCE_INSTALLATION = "installation"
_THEME_KEYS = ("bg", "surface", "text", "muted", "accent", "ok", "warn", "error")
LOCKABLE = frozenset({*(f"{theme}.{key}" for theme in ("light", "dark") for key in _THEME_KEYS),
                      "fonts.head", "fonts.body", "radius", "logo", "icons"})
_ID = re.compile(r"^[A-Za-z0-9_.-]{1,80}$")


class CorporateIdentityError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def normalize_workspace_profile_id(value: Any) -> str:
    found = str(value or "").strip()
    if found and not _ID.match(found):
        raise CorporateIdentityError("corp_identity_profile_invalid", "corp_identity_profile_id: a profile id")
    return found


async def _profiles(db: AsyncSession) -> dict[str, dict[str, Any]]:
    return {str(item.get("id") or ""): item for item in await load_registry(db) if item.get("id")}


async def effective_profile(db: AsyncSession, project_id: str | None) -> dict[str, Any]:
    profiles = await _profiles(db)
    chosen, source = "", SOURCE_INSTALLATION
    if project_id:
        from ...models import Project

        project = await db.get(Project, project_id)
        config = project.config if project is not None and isinstance(project.config, dict) else {}
        candidate = str(config.get(WORKSPACE_KEY) or "").strip()
        if candidate in profiles:
            chosen, source = candidate, SOURCE_WORKSPACE
    if not chosen:
        default = str(await get_system_config_value(db, CORP_IDENTITY_DEFAULT_PROFILE_KEY) or "").strip()
        chosen = default if default in profiles else ""
    profile = profiles.get(chosen) or {}
    return {"profile_id": chosen, "profile_name": str(profile.get("name") or ""), "source": source,
            "locks": sorted(set(profile.get(LOCKS_KEY) or []) & LOCKABLE),
            "updated_at": str(profile.get("updated_at") or "")}


async def assigned_profile_ids(db: AsyncSession) -> set[str]:
    from ...models import Project

    ids = {str(await get_system_config_value(db, CORP_IDENTITY_DEFAULT_PROFILE_KEY) or "").strip()}
    for config in (await db.execute(select(Project.config))).scalars():
        if isinstance(config, dict):
            ids.add(str(config.get(WORKSPACE_KEY) or "").strip())
    return ids - {""}


async def require_profile(db: AsyncSession, profile_id: str) -> None:
    if profile_id and profile_id not in await _profiles(db):
        raise CorporateIdentityError("corp_identity_profile_unknown", f"No corporate identity {profile_id}.")


async def set_studio_locks(db: AsyncSession, profile_id: str, paths: Any) -> list[str]:
    if not isinstance(paths, list) or not all(isinstance(path, str) for path in paths):
        raise CorporateIdentityError("studio_locks_invalid", "paths: a list of token paths")
    unknown = sorted(set(paths) - LOCKABLE)
    if unknown:
        raise CorporateIdentityError("studio_locks_invalid", f"Not lockable: {', '.join(unknown)}")
    registry = await load_registry(db)
    for item in registry:
        if str(item.get("id") or "") == profile_id:
            item[LOCKS_KEY] = sorted(set(paths))
            await save_registry(db, registry)
            return item[LOCKS_KEY]
    raise CorporateIdentityError("corp_identity_profile_unknown", f"No corporate identity {profile_id}.")


__all__ = ["LOCKABLE", "LOCKS_KEY", "WORKSPACE_KEY", "CorporateIdentityError", "assigned_profile_ids",
           "effective_profile", "normalize_workspace_profile_id", "require_profile", "set_studio_locks"]
