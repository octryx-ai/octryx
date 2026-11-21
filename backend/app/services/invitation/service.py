from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import timedelta

import bcrypt
from fastapi import HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...bcrypt_cost import bcrypt_salt
from ...models import Personality, Project, Role, Team, TeamMember, User, UserInvitation, UserProject, UserRole
from ...plugins import plugin_manager
from ...time_utils import ensure_utc, utc_now, utc_now_aware
from ..auth import hash_password
from ..team_notification import create_notification


def _hash_invitation_token(token: str) -> str:
    # bcrypt-of-sha256: a work-factor hash prevents brute-force of invitation tokens
    digest = hashlib.sha256(token.encode("utf-8")).digest()
    return bcrypt.hashpw(digest, bcrypt_salt()).decode("utf-8")


def _verify_invitation_token_bcrypt(token: str, stored_hash: str) -> bool:
    """Verify an invitation token against bcrypt-of-sha256 hash."""
    try:
        digest = hashlib.sha256(token.encode("utf-8")).digest()
        return bcrypt.checkpw(digest, stored_hash.encode("utf-8"))
    except Exception:
        return False


async def _is_admin(db: AsyncSession, user_id: str) -> bool:
    rows = await db.execute(
        select(Role.name).join(UserRole, UserRole.role_id == Role.id).where(UserRole.user_id == user_id)
    )
    return "admin" in {row[0] for row in rows.all()}


async def _send_invitation_email(email: str, invite_url: str) -> str:
    channel_tuple = plugin_manager.get_single_channel_for_plugin("email")
    if not channel_tuple:
        return "manual"
    _channel_id, plugin = channel_tuple
    subject = "Your Octryx invitation"
    content = f"You have been invited to Octryx.\n\nAccept your invitation here:\n{invite_url}\n"
    sent = await plugin.send_message(email, content, subject=subject)
    return "email" if sent else "manual"


def _serialize_invitation(invitation: UserInvitation, invite_url: str, delivery_method: str) -> dict:
    return {
        "id": invitation.id,
        "email": invitation.email,
        "team_id": invitation.team_id,
        "project_id": invitation.project_id,
        "role": invitation.role,
        "invite_url": invite_url,
        "delivery_method": delivery_method,
        "expires_at": ensure_utc(invitation.expires_at).isoformat() if invitation.expires_at else None,
        "accepted_at": ensure_utc(invitation.accepted_at).isoformat() if invitation.accepted_at else None,
    }


async def create_invitation(
    db: AsyncSession,
    *,
    current_user: User,
    request: Request,
    email: str,
    team_id: str | None,
    project_id: str | None,
    role: str,
    expires_in_hours: int,
) -> dict:
    if not await _is_admin(db, current_user.id):
        raise HTTPException(status_code=403, detail="Only admins can create invitations")
    normalized_email = email.strip().lower()
    if "@" not in normalized_email:
        raise HTTPException(status_code=400, detail="Valid email is required")
    if (await db.execute(select(User).where(User.email == normalized_email))).scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Email already registered")
    if team_id and not await db.get(Team, team_id):
        raise HTTPException(status_code=404, detail="Team not found")
    if project_id and not await db.get(Project, project_id):
        raise HTTPException(status_code=404, detail="Project not found")

    raw_token = secrets.token_urlsafe(32)
    invitation = UserInvitation(
        id=str(uuid.uuid4()),
        email=normalized_email,
        invited_by=current_user.id,
        team_id=team_id,
        project_id=project_id,
        role=role.strip().lower() or "member",
        token_hash=_hash_invitation_token(raw_token),
        expires_at=utc_now() + timedelta(hours=expires_in_hours),
    )
    db.add(invitation)
    await db.flush()
    invite_url = str(request.base_url).rstrip("/") + f"/admin/invitations/{raw_token}"
    delivery_method = await _send_invitation_email(normalized_email, invite_url)
    await db.commit()
    return _serialize_invitation(invitation, invite_url, delivery_method)


async def _valid_invitation(db: AsyncSession, token: str) -> UserInvitation:
    # bcrypt-of-sha256 verification — find valid invitation, then verify with work-factor hash
    invitation = None
    rows = await db.execute(
        select(UserInvitation).where(
            UserInvitation.accepted_at.is_(None),
            UserInvitation.expires_at > utc_now_aware(),
        )
    )
    for row in rows.scalars().all():
        if _verify_invitation_token_bcrypt(token, row.token_hash):
            invitation = row
            break
    if not invitation:
        raise HTTPException(status_code=404, detail="Invitation not found")
    if invitation.accepted_at:
        raise HTTPException(status_code=400, detail="Invitation already accepted")
    if ensure_utc(invitation.expires_at) <= utc_now_aware():
        raise HTTPException(status_code=400, detail="Invitation expired")
    return invitation


async def _create_invited_user(
    db: AsyncSession, invitation: UserInvitation, *, username: str, password: str, display_name: str | None
) -> User:
    user = User(
        id=str(uuid.uuid4()),
        username=username.strip(),
        email=invitation.email,
        password_hash=hash_password(password),
        display_name=(display_name or username).strip(),
        is_active=True,
    )
    db.add(user)
    await db.flush()

    viewer_role = (await db.execute(select(Role).where(Role.name == "viewer"))).scalar_one_or_none()
    if viewer_role is not None:
        db.add(UserRole(user_id=user.id, role_id=viewer_role.id))
    db.add(Personality(user_id=user.id))
    return user


async def _grant_invited_memberships(db: AsyncSession, invitation: UserInvitation, user: User) -> None:
    if invitation.team_id:
        existing_member = (
            await db.execute(
                select(TeamMember).where(TeamMember.team_id == invitation.team_id, TeamMember.user_id == user.id)
            )
        ).scalar_one_or_none()
        if existing_member is None:
            db.add(
                TeamMember(
                    team_id=invitation.team_id,
                    user_id=user.id,
                    role=invitation.role or "member",
                    added_by=invitation.invited_by,
                )
            )
    if invitation.project_id:
        existing_project = (
            await db.execute(
                select(UserProject).where(
                    UserProject.project_id == invitation.project_id,
                    UserProject.user_id == user.id,
                )
            )
        ).scalar_one_or_none()
        if existing_project is None:
            db.add(
                UserProject(
                    user_id=user.id,
                    project_id=invitation.project_id,
                    role=invitation.role or "member",
                    granted_by=invitation.invited_by,
                )
            )


async def accept_invitation(
    db: AsyncSession,
    *,
    token: str,
    username: str,
    password: str,
    display_name: str | None,
) -> dict:
    invitation = await _valid_invitation(db, token)
    if (await db.execute(select(User).where(User.username == username))).scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Username already exists")
    if (await db.execute(select(User).where(User.email == invitation.email))).scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Email already registered")

    user = await _create_invited_user(
        db, invitation, username=username, password=password, display_name=display_name
    )
    await _grant_invited_memberships(db, invitation, user)

    invitation.accepted_at = utc_now()
    await create_notification(
        db,
        user_id=invitation.invited_by,
        notification_type="invitation.accepted",
        title=f"Invitation accepted by {user.username}",
        body=f"{invitation.email} accepted the invitation.",
        link="/chat?area=admin&tab=users",
    )
    await db.commit()
    return {
        "user_id": user.id,
        "username": user.username,
        "email": user.email,
        "team_id": invitation.team_id,
        "project_id": invitation.project_id,
        "accepted_at": invitation.accepted_at.isoformat() if invitation.accepted_at else None,
    }
