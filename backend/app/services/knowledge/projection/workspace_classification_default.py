"""The Instance's default Workspace data classification, applied once. An existing classification is never overwritten,
and a cleared one is not refilled."""

from __future__ import annotations

import logging
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ....models import AuditLog, Project
from ...admin.project.admin_project_config_service import apply_project_config_patch
from ...model_gateway.data_policy.classification import (
    DATA_POLICY_CLASSIFICATION_FIELD,
    DATA_POLICY_CONFIG_KEY,
    normalized_classification,
    resolve_data_classification,
)
from ...system_config.values import set_system_config_value
from .workspace_classification_values import (
    _CONFIG_AUDIT_ACTION,
    DEFAULT_AUDIT_ACTION,
    INSTANCE_DEFAULT_AUDIT_ACTION,
    INSTANCE_DEFAULT_CONFIG_KEY,
    INSTANCE_DEFAULT_NONE,
    SOURCE_INSTANCE_DEFAULT,
    SOURCE_UNSET,
    SOURCE_WORKSPACE,
    WORKSPACE_CLASSIFICATION_AUDIT_ACTION,
    _declared,
    _known_admin_default,
    _may_default,
    _section,
    checked_classification,
    instance_default_for,
)

logger = logging.getLogger(__name__)


async def _last_default(db: AsyncSession, project_id: str) -> tuple[str, datetime] | None:
    row = (
        await db.execute(
            select(AuditLog.details, AuditLog.created_at)
            .where(AuditLog.action == DEFAULT_AUDIT_ACTION, AuditLog.resource_id == project_id)
            .order_by(AuditLog.created_at.desc())
            .limit(1)
        )
    ).first()
    if row is None:
        return None
    details = row.details if isinstance(row.details, dict) else {}
    return normalized_classification(details.get("classification")), row.created_at


async def _eligible(db: AsyncSession, project: Project) -> bool:
    return _may_default(project.config) and await _last_default(db, project.id) is None


def _default_audit(project_id: str, default: str, actor_id: str) -> AuditLog:
    return AuditLog(
        user_id=actor_id,
        action=DEFAULT_AUDIT_ACTION,
        resource_type="workspace",
        resource_id=project_id,
        details={"classification": default, "source": SOURCE_INSTANCE_DEFAULT},
    )


async def _write_default(db: AsyncSession, project: Project, default: str, actor_id: str) -> None:
    await apply_project_config_patch(
        db,
        project=project,
        patch={DATA_POLICY_CONFIG_KEY: {**_section(project.config), DATA_POLICY_CLASSIFICATION_FIELD: default}},
        actor_user_id=actor_id,
    )
    db.add(_default_audit(project.id, default, actor_id))


async def new_workspace_default(db: AsyncSession) -> str | None:
    default, _state, _source = await instance_default_for(db)
    return default


def stamp_new_workspace_default(db: AsyncSession, project: Project, default: str | None, actor_id: str) -> str | None:
    # A Workspace being created carries the default from its INSERT on. A separate write after the creation is a
    # read-then-write that SQLite refuses under parallel requests (a stale snapshot), and the refused write left the
    # creating request's transaction unusable for every later write.
    if default is None or not _may_default(project.config):
        return None
    config = dict(project.config or {})
    project.config = {**config, DATA_POLICY_CONFIG_KEY: {**_section(config), DATA_POLICY_CLASSIFICATION_FIELD: default}}
    db.add(_default_audit(project.id, default, actor_id))
    return default


async def apply_instance_default_classification(db: AsyncSession, *, project_id: str, actor_id: str) -> str | None:
    project: Project | None = None
    try:
        async with db.begin_nested():
            default, _state, _source = await instance_default_for(db)
            if default is None:
                return None
            project = (await db.execute(select(Project).where(Project.id == project_id))).scalar_one_or_none()
            if project is None or not await _eligible(db, project):
                return None
            await _write_default(db, project, default, actor_id)
    except Exception as error:  # noqa: BLE001 - enabling Knowledge must not fail on the default
        logger.warning(
            "Knowledge default data classification was not applied", extra={"error_class": type(error).__name__}
        )
        await _reload(db, project)
        return None
    return default


async def _reload(db: AsyncSession, project: Project | None) -> None:
    # The rolled-back savepoint expired the Workspace the caller holds; an attribute read would lazy-load in async code.
    if project is not None:
        await db.refresh(project)


async def _changed_by_settings_since(db: AsyncSession, project_id: str, since: datetime) -> bool:
    # A write that carried ``data_policy`` is the admin's own decision, even when it saves the default's value again.
    rows = (
        await db.execute(
            select(AuditLog.details).where(
                AuditLog.action == _CONFIG_AUDIT_ACTION,
                AuditLog.resource_id == project_id,
                AuditLog.created_at > since,
            )
        )
    ).scalars()
    for details in rows:
        if not isinstance(details, dict):
            continue
        patched = details.get("patched_keys")
        if isinstance(patched, list) and DATA_POLICY_CONFIG_KEY in patched:
            return True
        if _declared(details.get("before")) != _declared(details.get("after")):
            return True
    return False


async def workspace_classification_view(db: AsyncSession, project_id: str) -> dict[str, str | None]:
    config = (await db.execute(select(Project.config).where(Project.id == project_id))).scalar_one_or_none()
    section = config.get(DATA_POLICY_CONFIG_KEY) if isinstance(config, dict) else None
    resolved = resolve_data_classification(project_data_policy=section)
    declared = _declared(config)
    source = SOURCE_UNSET
    if declared:
        source = SOURCE_WORKSPACE
        last_default = await _last_default(db, project_id)
        if (
            last_default is not None
            and last_default[0] == declared
            and not await _changed_by_settings_since(db, project_id, last_default[1])
        ):
            source = SOURCE_INSTANCE_DEFAULT
    default, default_state, _default_source = await instance_default_for(db)
    return {
        "effective": resolved.classification or None,
        "source": source,
        "instance_default": default,
        "instance_default_state": default_state,
    }


async def eligible_workspace_ids(db: AsyncSession) -> list[str]:
    projects = (await db.execute(select(Project).order_by(Project.id))).scalars().all()
    return [project.id for project in projects if await _eligible(db, project)]


async def set_instance_default(
    db: AsyncSession, *, classification: object, actor_id: str, apply_to_unclassified: bool
) -> dict[str, object]:
    # A Workspace's own value, a cleared classification or an unreadable ``data_policy`` is never touched.
    value = checked_classification(classification)
    before, _state, before_source = await instance_default_for(db)
    await set_system_config_value(
        db, key=INSTANCE_DEFAULT_CONFIG_KEY, value=value or INSTANCE_DEFAULT_NONE,
        description="Level for new Workspaces",
        )
    _known_admin_default[:] = [(value,)]
    applied = 0
    if apply_to_unclassified and value is not None:
        for project_id in await eligible_workspace_ids(db):
            project = await db.get(Project, project_id)
            await _write_default(db, project, value, actor_id)
            applied += 1
    db.add(
        AuditLog(
            user_id=actor_id,
            action=INSTANCE_DEFAULT_AUDIT_ACTION,
            resource_type="system_config",
            resource_id=INSTANCE_DEFAULT_CONFIG_KEY,
            details={"before": before, "before_source": before_source, "after": value,
                     "apply_to_unclassified": bool(apply_to_unclassified), "applied_count": applied},
        )
    )
    await db.flush()
    return {"classification": value, "applied_count": applied}


async def set_workspace_classification(
    db: AsyncSession, *, project: Project, classification: object, actor_id: str
) -> str | None:
    # Clearing is recorded as ``classification_cleared``, so no Instance default ever refills it.
    value = checked_classification(classification)
    before = _declared(project.config) or None
    await apply_project_config_patch(
        db,
        project=project,
        patch={DATA_POLICY_CONFIG_KEY: {**_section(project.config), DATA_POLICY_CLASSIFICATION_FIELD: value or ""}},
        actor_user_id=actor_id,
    )
    db.add(
        AuditLog(
            user_id=actor_id,
            action=WORKSPACE_CLASSIFICATION_AUDIT_ACTION,
            resource_type="workspace",
            resource_id=project.id,
            details={"before": before, "after": value, "cleared": value is None},
        )
    )
    await db.flush()
    return value


__all__ = [
    "apply_instance_default_classification",
    "eligible_workspace_ids",
    "new_workspace_default",
    "set_instance_default",
    "set_workspace_classification",
    "stamp_new_workspace_default",
    "workspace_classification_view",
]
