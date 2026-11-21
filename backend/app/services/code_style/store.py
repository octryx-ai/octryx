"""Where each level of the style lives, and reading them together.

- installation: ``SystemConfig["code_style"]`` (JSON);
- Workspace: ``Project.config["code_style"]``;
- repository: ``CodeRepository.config_json["coding_setup"]["code_style"]``.

A level without a ``code_style`` of its own is empty (its parent decides). A stored value that does not validate is
ignored (the level falls back to its parent), never raised at a run.
"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from ...models import AuditLog, Project
from ...models.runtime.code_intelligence import CodeRepository
from .schema import normalize_profile
from .schema_values import CodeStyleError

INSTALLATION_KEY = "code_style"
CONFIG_KEY = "code_style"
AUDIT_ACTION = "admin.code_style_updated"


def _valid(value: Any, path: str) -> dict[str, Any]:
    try:
        return normalize_profile(value, path)
    except CodeStyleError:
        return {}


async def installation_profile(db: AsyncSession) -> dict[str, Any]:
    from ..system_config.values import get_system_config_value

    raw = await get_system_config_value(db, INSTALLATION_KEY)
    try:
        return _valid(json.loads(raw) if raw else None, "installation")
    except ValueError:
        return {}


def workspace_profile(project: Project | None) -> dict[str, Any]:
    config = dict(project.config or {}) if project is not None and isinstance(project.config, dict) else {}
    return _valid(config[CONFIG_KEY], "workspace") if isinstance(config.get(CONFIG_KEY), dict) else {}


def repository_profile(record: CodeRepository | None) -> dict[str, Any]:
    setup = dict(dict(record.config_json or {}).get("coding_setup") or {}) if record is not None else {}
    return _valid(setup.get(CONFIG_KEY), "repository") if isinstance(setup.get(CONFIG_KEY), dict) else {}


async def levels(db: AsyncSession, *, project: Project | None, record: CodeRepository | None) -> dict[str, Any]:
    return {"installation": await installation_profile(db), "workspace": workspace_profile(project),
            "repository": repository_profile(record)}


def _audit(db: AsyncSession, actor_id: str, level: str, resource_id: str, profile: dict[str, Any]) -> None:
    db.add(AuditLog(user_id=actor_id, action=AUDIT_ACTION, resource_type=f"code_style_{level}",
                    resource_id=resource_id, details={"profile": profile}))


async def set_installation_profile(db: AsyncSession, value: Any, *, actor_id: str) -> dict[str, Any]:
    from ..system_config.values import set_system_config_value

    profile = normalize_profile(value, "installation")
    await set_system_config_value(db, key=INSTALLATION_KEY, value=json.dumps(profile) if profile else None,
                                  description="The installation's code style", updated_by=actor_id,
                                  record_prompt_revision=False)
    _audit(db, actor_id, "installation", INSTALLATION_KEY, profile)
    await db.flush()
    return profile


async def set_workspace_profile(db: AsyncSession, project: Project, value: Any, *, actor_id: str) -> dict[str, Any]:
    profile = normalize_profile(value, "workspace")
    project.config = {**dict(project.config or {}), CONFIG_KEY: profile}
    flag_modified(project, "config")
    _audit(db, actor_id, "workspace", project.id, profile)
    await db.flush()
    return profile


async def set_repository_profile(db: AsyncSession, record: CodeRepository, value: Any, *,
                                 actor_id: str) -> dict[str, Any]:
    profile = normalize_profile(value, "repository")
    config = dict(record.config_json or {})
    config["coding_setup"] = {**dict(config.get("coding_setup") or {}), CONFIG_KEY: profile}
    record.config_json = config
    flag_modified(record, "config_json")
    _audit(db, actor_id, "repository", record.id, profile)
    await db.flush()
    return profile


__all__ = ["levels", "installation_profile", "repository_profile", "set_installation_profile",
           "set_repository_profile", "set_workspace_profile", "workspace_profile"]
