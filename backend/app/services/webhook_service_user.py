"""The least-privilege principal an inbound webhook run executes as.

A webhook trigger is an unauthenticated caller holding a shared secret, so its agent run must not
inherit the rights of the admin who created the webhook. Each webhook gets its own service user,
modelled on the channel service user (``channel_config/service_user.py``):

* username ``webhook-service-<webhook id>``, an undeliverable ``.invalid`` email address;
* ``account_type``/``auth_source`` ``webhook_service`` and a password nobody knows, so it cannot
  log in; no API key;
* exactly the global ``viewer`` role and one ``viewer`` membership in the webhook's Workspace.

:func:`ensure_webhook_service_user` creates or repairs it (idempotent) and is called on every
trigger, so a webhook without its principal gets one on first use. A username held
by another kind of account is refused (``webhook_service_user_not_configured``), never reused.
"""

from __future__ import annotations

import secrets
import uuid

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import ProjectUserRoleAssignment, Role, User, UserProject, UserRole
from ..models.integration.webhook import Webhook

STATE_WEBHOOK_SERVICE_USER_NOT_CONFIGURED = "webhook_service_user_not_configured"
ACCOUNT_TYPE_WEBHOOK_SERVICE = "webhook_service"
SERVICE_USER_ROLE = "viewer"
SERVICE_USER_PROJECT_ROLE = "viewer"
_EMAIL_DOMAIN = "webhook-service.octryx.invalid"


async def _already_bound(db: AsyncSession, user_id: str, project_id: str) -> bool:
    role_query = select(Role.name).join(UserRole, UserRole.role_id == Role.id).where(UserRole.user_id == user_id)
    roles = (await db.execute(role_query)).scalars().all()
    memberships = (
        await db.execute(select(UserProject.project_id, UserProject.role).where(UserProject.user_id == user_id))
    ).all()
    assignments = (
        await db.execute(
            select(ProjectUserRoleAssignment.project_id, ProjectUserRoleAssignment.role_name)
            .where(ProjectUserRoleAssignment.user_id == user_id)
        )
    ).all()
    wanted = [(project_id, SERVICE_USER_PROJECT_ROLE)]
    return (
        list(roles) == [SERVICE_USER_ROLE]
        and [tuple(row) for row in memberships] == wanted
        and [tuple(row) for row in assignments] == wanted
    )


class WebhookServiceUserConflictError(RuntimeError):
    """The service username is taken by an account that is not this webhook's service user."""


def webhook_service_username(webhook_id: str) -> str:
    return f"webhook-service-{webhook_id}"


async def ensure_webhook_service_user(db: AsyncSession, webhook: Webhook) -> User:
    """Create or repair ``webhook``'s service user; flushes, the caller commits."""
    from .auth import hash_password

    username = webhook_service_username(webhook.id)
    user = (await db.execute(select(User).where(User.username == username))).scalar_one_or_none()
    if user is not None and user.account_type != ACCOUNT_TYPE_WEBHOOK_SERVICE:
        raise WebhookServiceUserConflictError(f"username '{username}' belongs to another account")
    if user is None:
        user = User(
            id=str(uuid.uuid4()),
            username=username,
            email=f"{username}@{_EMAIL_DOMAIN}",
            password_hash=hash_password(secrets.token_urlsafe(48)),
            auth_source=ACCOUNT_TYPE_WEBHOOK_SERVICE,
            account_type=ACCOUNT_TYPE_WEBHOOK_SERVICE,
            display_name=f"{webhook.name} (webhook service)"[:200],
            is_active=True,
        )
        db.add(user)
        await db.flush()
    user.is_active = True
    if await _already_bound(db, user.id, webhook.project_id):
        # Idempotent: nothing is deleted and re-inserted when the membership already matches, so concurrent
        # alerts never collide on the membership unique indexes.
        return user
    viewer = (await db.execute(select(Role).where(Role.name == SERVICE_USER_ROLE))).scalar_one_or_none()
    if viewer is None:
        raise RuntimeError(f"The '{SERVICE_USER_ROLE}' role is not seeded")
    await db.execute(delete(UserRole).where(UserRole.user_id == user.id))
    db.add(UserRole(user_id=user.id, role_id=viewer.id))
    await db.execute(delete(ProjectUserRoleAssignment).where(ProjectUserRoleAssignment.user_id == user.id))
    await db.execute(delete(UserProject).where(UserProject.user_id == user.id))
    db.add(UserProject(user_id=user.id, project_id=webhook.project_id, role=SERVICE_USER_PROJECT_ROLE))
    db.add(
        ProjectUserRoleAssignment(user_id=user.id, project_id=webhook.project_id, role_name=SERVICE_USER_PROJECT_ROLE)
    )
    await db.flush()
    return user


__all__ = [
    "ACCOUNT_TYPE_WEBHOOK_SERVICE",
    "STATE_WEBHOOK_SERVICE_USER_NOT_CONFIGURED",
    "WebhookServiceUserConflictError",
    "ensure_webhook_service_user",
    "webhook_service_username",
]
