"""The Workspace's Memory settings, stored on its own project row. Never read from the merged turn configuration, which
agent-writable entries reach."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from ....models import Project

MEMORY_POLICY_KEY = "knowledge_memory_policy"
AUTOMATIC_CAPTURE = "automatic_capture"
# Lessons learned from octryx sessions (off by default) and who may confirm them (by role).
SESSION_LESSONS = "session_lessons"
CONFIRM_ROLES = "confirm_roles"
CONFIRM_ROLE_CHOICES = ("viewer", "member", "owner", "admin")
DEFAULT_CONFIRM_ROLES = ("owner", "admin")


def automatic_capture_of(config: object) -> bool:
    policy = config.get(MEMORY_POLICY_KEY) if isinstance(config, dict) else None
    # Only an explicit boolean true enables it; anything else is the default, off.
    return isinstance(policy, dict) and policy.get(AUTOMATIC_CAPTURE) is True


async def automatic_capture_enabled(db: AsyncSession, project_id: str | None) -> bool:
    if not project_id:
        return False
    config = (await db.execute(select(Project.config).where(Project.id == project_id))).scalar_one_or_none()
    return automatic_capture_of(config)


def _policy(config: object) -> dict:
    policy = config.get(MEMORY_POLICY_KEY) if isinstance(config, dict) else None
    return policy if isinstance(policy, dict) else {}


def session_lessons_of(config: object) -> bool:
    return _policy(config).get(SESSION_LESSONS) is True


def confirm_roles_of(config: object) -> tuple[str, ...]:
    stored = _policy(config).get(CONFIRM_ROLES)
    if not isinstance(stored, list):
        return DEFAULT_CONFIRM_ROLES
    return tuple(role for role in CONFIRM_ROLE_CHOICES if role in stored)


async def _config(db: AsyncSession, project_id: str | None) -> object:
    if not project_id:
        return None
    return (await db.execute(select(Project.config).where(Project.id == project_id))).scalar_one_or_none()


async def session_lessons_enabled(db: AsyncSession, project_id: str | None) -> bool:
    return session_lessons_of(await _config(db, project_id))


async def confirm_roles(db: AsyncSession, project_id: str | None) -> tuple[str, ...]:
    return confirm_roles_of(await _config(db, project_id))


async def set_memory_policy(db: AsyncSession, project_id: str, **values: object) -> None:
    project = await db.get(Project, project_id)
    if project is None:
        return
    config = dict(project.config or {})
    policy = dict(_policy(config))
    policy.update(values)
    config[MEMORY_POLICY_KEY] = policy
    project.config = config
    flag_modified(project, "config")
    await db.flush()


async def set_automatic_capture(db: AsyncSession, project_id: str, *, enabled: bool) -> None:
    project = await db.get(Project, project_id)
    if project is None:
        return
    config = dict(project.config or {})
    policy = dict(config.get(MEMORY_POLICY_KEY) or {}) if isinstance(config.get(MEMORY_POLICY_KEY), dict) else {}
    policy[AUTOMATIC_CAPTURE] = bool(enabled)
    config[MEMORY_POLICY_KEY] = policy
    project.config = config
    flag_modified(project, "config")
    await db.flush()


__all__ = [
    "CONFIRM_ROLES",
    "CONFIRM_ROLE_CHOICES",
    "DEFAULT_CONFIRM_ROLES",
    "MEMORY_POLICY_KEY",
    "SESSION_LESSONS",
    "confirm_roles",
    "confirm_roles_of",
    "session_lessons_enabled",
    "session_lessons_of",
    "set_memory_policy",
    "automatic_capture_enabled",
    "automatic_capture_of",
    "set_automatic_capture",
]
