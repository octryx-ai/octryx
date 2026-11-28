"""The dedicated service user of one channel."""

from __future__ import annotations

import logging
import secrets
import uuid

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import ProjectUserRoleAssignment, Role, User, UserProject, UserRole
from ...models.integration.channel_config import ChannelConfig

logger = logging.getLogger(__name__)

STATE_SERVICE_USER_NOT_CONFIGURED = "channel_service_user_not_configured"
ACCOUNT_TYPE_CHANNEL_SERVICE = "channel_service"
SERVICE_USER_ROLE = "viewer"
SERVICE_USER_PROJECT_ROLE = "viewer"
_EMAIL_DOMAIN = "channel-service.octryx.invalid"


class ChannelServiceUserConflictError(RuntimeError):
    pass


def service_username(channel_id: int | str) -> str:
    return f"channel-service-{channel_id}"


def _service_email(channel_id: int | str) -> str:
    return f"{service_username(channel_id)}@{_EMAIL_DOMAIN}"


async def _viewer_role(db: AsyncSession) -> Role:
    role = (await db.execute(select(Role).where(Role.name == SERVICE_USER_ROLE))).scalar_one_or_none()
    if role is None:
        raise RuntimeError(f"The '{SERVICE_USER_ROLE}' role is not seeded")
    return role


async def ensure_channel_service_user(db: AsyncSession, channel: ChannelConfig) -> User:
    from ..auth import hash_password

    username = service_username(channel.id)
    user = (await db.execute(select(User).where(User.username == username))).scalar_one_or_none()
    if user is not None and user.account_type != ACCOUNT_TYPE_CHANNEL_SERVICE:
        raise ChannelServiceUserConflictError(f"username '{username}' belongs to another account")
    if user is None:
        user = User(
            id=str(uuid.uuid4()),
            username=username,
            email=_service_email(channel.id),
            password_hash=hash_password(secrets.token_urlsafe(48)),
            auth_source=ACCOUNT_TYPE_CHANNEL_SERVICE,
            account_type=ACCOUNT_TYPE_CHANNEL_SERVICE,
            display_name=f"{channel.name} (channel service)"[:200],
            is_active=True,
        )
        db.add(user)
        await db.flush()
    user.is_active = True
    viewer = await _viewer_role(db)
    await db.execute(delete(UserRole).where(UserRole.user_id == user.id))
    db.add(UserRole(user_id=user.id, role_id=viewer.id))
    await db.execute(delete(ProjectUserRoleAssignment).where(ProjectUserRoleAssignment.user_id == user.id))
    await db.execute(delete(UserProject).where(UserProject.user_id == user.id))
    if channel.project_id:
        db.add(UserProject(user_id=user.id, project_id=channel.project_id, role=SERVICE_USER_PROJECT_ROLE))
        db.add(
            ProjectUserRoleAssignment(
                user_id=user.id, project_id=channel.project_id, role_name=SERVICE_USER_PROJECT_ROLE
            )
        )
    await db.flush()
    return user


async def deactivate_channel_service_user(db: AsyncSession, channel_id: int | str) -> None:
    user = (
        await db.execute(select(User).where(User.username == service_username(channel_id)))
    ).scalar_one_or_none()
    if user is not None and user.account_type == ACCOUNT_TYPE_CHANNEL_SERVICE:
        user.is_active = False
        await db.flush()


async def resolve_channel_service_user_id(
    db: AsyncSession, channel_id: int | str, project_id: str | None
) -> str | None:
    user = (
        await db.execute(
            select(User).where(
                User.username == service_username(channel_id),
                User.account_type == ACCOUNT_TYPE_CHANNEL_SERVICE,
                User.is_active.is_(True),
            )
        )
    ).scalar_one_or_none()
    if user is None:
        return None
    role_rows = await db.execute(
        select(Role.name).join(UserRole, UserRole.role_id == Role.id).where(UserRole.user_id == user.id)
    )
    roles = set(role_rows.scalars().all())
    if roles != {SERVICE_USER_ROLE}:
        logger.warning("channel.service_user.refused", extra={"reason": "roles_not_viewer_only"})
        return None
    if project_id:
        membership = (
            await db.execute(
                select(UserProject.role).where(UserProject.user_id == user.id, UserProject.project_id == project_id)
            )
        ).scalar_one_or_none()
        if membership != SERVICE_USER_PROJECT_ROLE:
            logger.warning("channel.service_user.refused", extra={"reason": "workspace_membership_not_viewer"})
            return None
    return user.id


__all__ = [
    "ACCOUNT_TYPE_CHANNEL_SERVICE",
    "STATE_SERVICE_USER_NOT_CONFIGURED",
    "ChannelServiceUserConflictError",
    "deactivate_channel_service_user",
    "ensure_channel_service_user",
    "resolve_channel_service_user_id",
    "service_username",
]
