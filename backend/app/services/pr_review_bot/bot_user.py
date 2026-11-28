"""The principal the review bot's runs start as: one service user per Workspace (concept §8)."""

from __future__ import annotations

import secrets
import uuid

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import ProjectUserRoleAssignment, Role, User, UserProject, UserRole
from ..webhook_service_user import SERVICE_USER_PROJECT_ROLE, SERVICE_USER_ROLE, _already_bound

ACCOUNT_TYPE_REVIEW_BOT = "review_bot_service"
DISPLAY_NAME = "Octryx review bot"
_EMAIL_DOMAIN = "review-bot.octryx.invalid"


class ReviewBotUserConflictError(RuntimeError):
    pass


def review_bot_username(project_id: str) -> str:
    return f"review-bot-{project_id}"


async def ensure_review_bot_user(db: AsyncSession, project_id: str) -> User:
    from ..auth import hash_password

    username = review_bot_username(project_id)
    user = (await db.execute(select(User).where(User.username == username))).scalar_one_or_none()
    if user is not None and user.account_type != ACCOUNT_TYPE_REVIEW_BOT:
        raise ReviewBotUserConflictError(f"username '{username}' belongs to another account")
    if user is None:
        user = User(id=str(uuid.uuid4()), username=username, email=f"{username}@{_EMAIL_DOMAIN}",
                    password_hash=hash_password(secrets.token_urlsafe(48)), auth_source=ACCOUNT_TYPE_REVIEW_BOT,
                    account_type=ACCOUNT_TYPE_REVIEW_BOT, display_name=DISPLAY_NAME, is_active=True)
        db.add(user)
        await db.flush()
    user.is_active = True
    if await _already_bound(db, user.id, project_id):
        return user
    viewer = (await db.execute(select(Role).where(Role.name == SERVICE_USER_ROLE))).scalar_one_or_none()
    if viewer is None:
        raise RuntimeError(f"The '{SERVICE_USER_ROLE}' role is not seeded")
    await db.execute(delete(UserRole).where(UserRole.user_id == user.id))
    db.add(UserRole(user_id=user.id, role_id=viewer.id))
    await db.execute(delete(ProjectUserRoleAssignment).where(ProjectUserRoleAssignment.user_id == user.id))
    await db.execute(delete(UserProject).where(UserProject.user_id == user.id))
    db.add(UserProject(user_id=user.id, project_id=project_id, role=SERVICE_USER_PROJECT_ROLE))
    db.add(ProjectUserRoleAssignment(user_id=user.id, project_id=project_id, role_name=SERVICE_USER_PROJECT_ROLE))
    await db.flush()
    return user


__all__ = ["ACCOUNT_TYPE_REVIEW_BOT", "DISPLAY_NAME", "ReviewBotUserConflictError", "ensure_review_bot_user",
           "review_bot_username"]
