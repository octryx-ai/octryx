"""A person's private Workspace.

- Every person gets exactly one, created on first use (:func:`ensure_private_workspace`): a project with
  ``access_mode == "private"`` and ``owner_user_id``; the owner is its only member (``UserProject`` role ``owner``).
- It is the person's default Workspace (the chat's start and the phone's start).
- **Only the owner has a role in it.** Platform admins get none: not through the admin role, not through a group,
  a global-role rule or an added membership (:func:`private_role`, used by ``access_control`` and
  ``project.service``). Admin surfaces that list or open projects leave other people's private Workspaces out
  (:func:`hidden_private_ids`, :func:`refuse_foreign_private`); they may show that one exists, never its content.
- Its name is unique per person (``projects.name`` is unique); the UI shows it as "Private".
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable

from sqlalchemy import and_, select
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
    """The only role anybody has in a private Workspace: ``owner`` for its owner, nothing for everyone else."""
    if not is_private(project):
        return None
    return OWNER_ROLE if project.owner_user_id and str(project.owner_user_id) == str(user_id) else None


async def private_project(db: AsyncSession, project_id: str) -> Project | None:
    """The project when it is a private Workspace, else ``None`` (one indexed lookup)."""
    if not project_id:
        return None
    project = await db.get(Project, project_id)
    return project if is_private(project) else None


async def hidden_private_ids(db: AsyncSession, user_id: str) -> set[str]:
    """Every private Workspace that is not ``user_id``'s own: what admin lists and scopes leave out."""
    rows = await db.execute(
        select(Project.id).where(Project.access_mode == PRIVATE_ACCESS_MODE,
                                 (Project.owner_user_id != str(user_id)) | Project.owner_user_id.is_(None))
    )
    return {str(row[0]) for row in rows.all()}


def foreign_private_filter(user_id: str):
    """A SQL condition on ``Project`` that keeps everything except other people's private Workspaces."""
    return (Project.access_mode != PRIVATE_ACCESS_MODE) | and_(
        Project.access_mode == PRIVATE_ACCESS_MODE, Project.owner_user_id == str(user_id))


async def refuse_foreign_private(db: AsyncSession, project_id: str, user_id: str) -> bool:
    """``True`` when ``project_id`` is somebody else's private Workspace (the caller answers 404)."""
    project = await private_project(db, project_id)
    return project is not None and private_role(project, user_id) is None


async def refuse_foreign_private_session(db: AsyncSession, session_id: str | None, user_id: str) -> bool:
    """``True`` when the session lies in somebody else's private Workspace."""
    from ...models import Session  # noqa: PLC0415

    session = await db.get(Session, str(session_id)) if session_id else None
    return bool(session is not None and session.project_id
                and await refuse_foreign_private(db, session.project_id, user_id))


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
    """Apply the default Workspace's policy when **it** changed since the last time. ``True`` when it changed.

    Keys the default does not have are left alone (the creation defaults stay: trace capture,
    the instance classification), and between two changes of the default the owner's own narrowing stays.
    """
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
    project = _new(user, name)
    async with db.begin_nested():
        db.add(project)
        await db.flush()
        db.add(UserProject(user_id=str(user.id), project_id=project.id, role=OWNER_ROLE, granted_by=str(user.id),
                           granted_at=utc_now()))
        await db.flush()
    # Like every Workspace at creation (project_lifecycle_service): the Instance default classification level.
    from ..knowledge.projection.workspace_classification_default import (  # noqa: PLC0415
        apply_instance_default_classification,
    )

    await apply_instance_default_classification(db, project_id=project.id, actor_id=str(user.id))
    return project


async def ensure_private_workspace(db: AsyncSession, user: User) -> Project:
    """The person's private Workspace, created on first use (idempotent, race-safe) with the default Workspace's
    policy (:data:`TEMPLATE_KEYS`). Flushes."""
    existing = await owned_private_workspace(db, str(user.id))
    if existing is not None:
        return existing
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
    "DISPLAY_NAME", "OWNER_ROLE", "PRIVATE_ACCESS_MODE", "REASON_PRIVATE_WORKSPACE", "ensure_private_workspace",
    "foreign_private_filter", "hidden_private_ids", "is_private", "owned_private_workspace", "private_project",
    "private_role", "refuse_foreign_private", "refuse_foreign_private_session", "sync_template_policy",
    "template_policy", "without_foreign_private",
]
