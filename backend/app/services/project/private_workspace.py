"""A person's private Workspace."""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from dataclasses import dataclass

from sqlalchemy import and_, column, select, table
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import Project, User, UserProject
from ...time_utils import utc_now

PRIVATE_ACCESS_MODE = "private"
PRIVATE_SOURCE_TYPE = "private"
OWNER_ROLE = "owner"
DISPLAY_NAME = "Private"
REASON_PRIVATE_WORKSPACE = "private_workspace"


def is_private(project: Project | None) -> bool:
    return project is not None and project.access_mode == PRIVATE_ACCESS_MODE


def private_role(project: Project | None, user_id: str) -> str | None:
    if not is_private(project):
        return None
    return OWNER_ROLE if project.owner_user_id and str(project.owner_user_id) == str(user_id) else None


def foreign_private(project: Project | None, user_id: str) -> bool:
    return is_private(project) and private_role(project, user_id) is None


# Which Workspaces are private and whose, whoever reads: the Workspace filter hides other people's private Workspaces,
# and a check that must tell them apart from shared ones cannot read them through it.
_PRIVACY = table("projects", column("id"), column("access_mode"), column("owner_user_id"))
_SESSION_WORKSPACE = table("sessions", column("id"), column("project_id"))


@dataclass(frozen=True)
class PrivateWorkspace:
    id: str
    owner_user_id: str | None
    access_mode: str = PRIVATE_ACCESS_MODE


async def private_project(db: AsyncSession, project_id: str) -> PrivateWorkspace | None:
    if not project_id:
        return None
    row = (await db.execute(select(_PRIVACY.c.owner_user_id).where(
        _PRIVACY.c.id == str(project_id), _PRIVACY.c.access_mode == PRIVATE_ACCESS_MODE))).first()
    return PrivateWorkspace(str(project_id), row[0]) if row is not None else None


def _foreign_private_ids(user_id: str):
    return select(_PRIVACY.c.id).where(_PRIVACY.c.access_mode == PRIVATE_ACCESS_MODE,
                                       (_PRIVACY.c.owner_user_id != str(user_id)) | _PRIVACY.c.owner_user_id.is_(None))


async def hidden_private_ids(db: AsyncSession, user_id: str) -> set[str]:
    return {str(row[0]) for row in (await db.execute(_foreign_private_ids(user_id))).all()}


def outside_foreign_private(column, user_id: str):
    return column.is_(None) | column.not_in(_foreign_private_ids(user_id))


def foreign_private_filter(user_id: str):
    return (Project.access_mode != PRIVATE_ACCESS_MODE) | and_(
        Project.access_mode == PRIVATE_ACCESS_MODE, Project.owner_user_id == str(user_id))


async def refuse_foreign_private(db: AsyncSession, project_id: str, user_id: str) -> bool:
    return foreign_private(await private_project(db, project_id), user_id)


async def refuse_foreign_private_session(db: AsyncSession, session_id: str | None, user_id: str) -> bool:
    workspace_id = (await db.execute(select(_SESSION_WORKSPACE.c.project_id).where(
        _SESSION_WORKSPACE.c.id == str(session_id)))).scalar_one_or_none() if session_id else None
    return bool(workspace_id and await refuse_foreign_private(db, workspace_id, user_id))


def without_foreign_private(project_ids: Iterable[str], hidden: set[str]) -> list[str]:
    return [project_id for project_id in project_ids if project_id not in hidden]


async def owned_private_workspace(db: AsyncSession, user_id: str) -> Project | None:
    return (await db.execute(
        select(Project).where(Project.access_mode == PRIVATE_ACCESS_MODE, Project.owner_user_id == str(user_id))
        .order_by(Project.created_at).limit(1)
    )).scalar_one_or_none()


def _name(user: User) -> str:
    handle = str(getattr(user, "username", "") or getattr(user, "email", "") or user.id)[:120]
    return f"{DISPLAY_NAME} · {handle}"


# The policy a private Workspace takes from the Instance's default Workspace: the same model grant,
# data classification, seat rule, cost limits and trace capture as everybody's default. Admins
# maintain these once, on the default Workspace, for every private Workspace; they never open a private one.
# ``knowledge_episode_policy`` is the owner's choice and never inherited (private chats must
# not be summarised into knowledge because an admin switched it on in the default Workspace).
TEMPLATE_KEYS = ("model_policy", "data_policy", "trace_capture", "agent_gateway_policy", "runtime_cost_limits")
TEMPLATE_DIGEST_KEY = "private_template_digest"


async def template_policy(db: AsyncSession) -> dict:
    from .default_workspace import default_workspace_id  # noqa: PLC0415

    default_id = await default_workspace_id(db)
    template = await db.get(Project, default_id) if default_id else None
    if template is None or is_private(template) or not isinstance(template.config, dict):
        return {}
    return {key: template.config[key] for key in TEMPLATE_KEYS if key in template.config}


async def sync_template_policy(db: AsyncSession, project: Project) -> bool:
    if not is_private(project):
        return False
    import hashlib  # noqa: PLC0415
    import json  # noqa: PLC0415

    policy = await template_policy(db)
    digest = hashlib.sha256(json.dumps(policy, sort_keys=True, default=str).encode()).hexdigest()[:32]
    config = dict(project.config or {})
    if config.get(TEMPLATE_DIGEST_KEY) == digest:
        return False
    project.config = {**config, **policy, TEMPLATE_DIGEST_KEY: digest}
    await db.flush()
    return True


def _new(user: User, name: str) -> Project:
    from ..trace_capture import ensure_default_trace_capture_config  # noqa: PLC0415

    return Project(id=str(uuid.uuid4()), name=name, config=ensure_default_trace_capture_config({}), is_active=True,
                   source_type=PRIVATE_SOURCE_TYPE,
                   description="Your private Workspace. Only you can see it; platform admins cannot.",
                   is_system=False, access_mode=PRIVATE_ACCESS_MODE, owner_user_id=str(user.id))


async def _create(db: AsyncSession, user: User, name: str) -> Project:
    # Like every Workspace at creation (project_lifecycle_service): the Instance default classification level.
    from ..knowledge.projection.workspace_classification_default import (  # noqa: PLC0415
        new_workspace_default,
        stamp_new_workspace_default,
    )

    default = await new_workspace_default(db)
    project = _new(user, name)
    async with db.begin_nested():
        stamp_new_workspace_default(db, project, default, str(user.id))
        db.add(project)
        await db.flush()
        db.add(UserProject(user_id=str(user.id), project_id=project.id, role=OWNER_ROLE, granted_by=str(user.id),
                           granted_at=utc_now()))
        await db.flush()
    # Without an Instance default Workspace there is no template grant; a fresh install still needs a usable model.
    from ..project_lifecycle_service import allow_all_cleared_models  # noqa: PLC0415

    await allow_all_cleared_models(db, project.id, actor_id=str(user.id))
    return project


async def ensure_private_workspace(db: AsyncSession, user: User) -> Project:
    existing = await owned_private_workspace(db, str(user.id))
    if existing is not None:
        return existing
    if (await db.execute(select(_PRIVACY.c.id).where(_PRIVACY.c.access_mode == PRIVATE_ACCESS_MODE,
                                                     _PRIVACY.c.owner_user_id == str(user.id)))).first():
        # A parallel request of the same person may have committed it between the two reads: then it is visible now.
        existing = await owned_private_workspace(db, str(user.id))
        if existing is not None:
            return existing
        from ..data_access.read_filter import HiddenWorkspaceError  # noqa: PLC0415

        raise HiddenWorkspaceError(f"the private Workspace of {user.id}")
    try:
        project = await _create(db, user, _name(user))
    except IntegrityError:
        # A parallel request created it, or another project already has the name.
        existing = await owned_private_workspace(db, str(user.id))
        if existing is not None:
            return existing
        project = await _create(db, user, f"{_name(user)} · {uuid.uuid4().hex[:8]}")
    await sync_template_policy(db, project)
    return project


__all__ = [
    "DISPLAY_NAME", "OWNER_ROLE", "PRIVATE_ACCESS_MODE", "REASON_PRIVATE_WORKSPACE", "PrivateWorkspace",
    "ensure_private_workspace",
    "foreign_private", "foreign_private_filter", "hidden_private_ids", "is_private", "outside_foreign_private",
    "owned_private_workspace", "private_project", "private_role", "refuse_foreign_private",
    "refuse_foreign_private_session", "sync_template_policy", "template_policy", "without_foreign_private",
]
