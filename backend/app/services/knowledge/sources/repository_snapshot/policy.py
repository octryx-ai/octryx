"""Whether a Workspace accepts local repository snapshots from its members' checkouts. Off by default; only an explicit
``true`` on the Workspace row enables it."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from .....models import AuditLog, Project

REPOSITORY_POLICY_KEY = "knowledge_repository_policy"
ALLOW_LOCAL_SNAPSHOTS = "allow_local_snapshots"
POLICY_AUDIT_ACTION = "knowledge.repository_policy.update"
REASON_LOCAL_SNAPSHOTS_NOT_ALLOWED = "local_snapshots_not_allowed"


def _policy_of(config: object) -> dict:
    policy = config.get(REPOSITORY_POLICY_KEY) if isinstance(config, dict) else None
    return policy if isinstance(policy, dict) else {}


def local_snapshots_allowed_by(config: object) -> bool:
    return _policy_of(config).get(ALLOW_LOCAL_SNAPSHOTS) is True


async def local_snapshots_allowed(db: AsyncSession, project_id: str) -> bool:
    config = (await db.execute(select(Project.config).where(Project.id == project_id))).scalar_one_or_none()
    return local_snapshots_allowed_by(config)


async def set_local_snapshots_allowed(db: AsyncSession, project_id: str, *, allowed: bool, actor_id: str) -> None:
    project = await db.get(Project, project_id)
    if project is None:
        return
    config = dict(project.config or {})
    policy = dict(_policy_of(config))
    old = policy.get(ALLOW_LOCAL_SNAPSHOTS) is True
    policy[ALLOW_LOCAL_SNAPSHOTS] = bool(allowed)
    config[REPOSITORY_POLICY_KEY] = policy
    project.config = config
    flag_modified(project, "config")
    if old != bool(allowed):
        db.add(
            AuditLog(
                user_id=actor_id,
                action=POLICY_AUDIT_ACTION,
                resource_type="workspace",
                resource_id=project_id,
                details={"workspace_id": project_id, "changes": {ALLOW_LOCAL_SNAPSHOTS: {"old": old, "new": allowed}}},
            )
        )
    await db.flush()


__all__ = [
    "ALLOW_LOCAL_SNAPSHOTS",
    "POLICY_AUDIT_ACTION",
    "REASON_LOCAL_SNAPSHOTS_NOT_ALLOWED",
    "REPOSITORY_POLICY_KEY",
    "local_snapshots_allowed",
    "local_snapshots_allowed_by",
    "set_local_snapshots_allowed",
]
