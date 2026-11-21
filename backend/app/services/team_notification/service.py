from __future__ import annotations

import uuid
from collections.abc import Iterable

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import (
    Notification,
    NotificationPreference,
    Project,
    Role,
    Team,
    TeamMember,
    TeamProject,
    User,
    UserProject,
    UserRole,
)
from ...time_utils import utc_now

TEAM_MEMBER_ROLES = {"owner", "admin", "member", "viewer"}


async def _user_role_names(db: AsyncSession, user_id: str) -> set[str]:
    rows = await db.execute(
        select(Role.name).join(UserRole, UserRole.role_id == Role.id).where(UserRole.user_id == user_id)
    )
    return {row[0] for row in rows.all()}


async def _is_global_admin(db: AsyncSession, user_id: str) -> bool:
    return "admin" in await _user_role_names(db, user_id)


async def _team_membership(db: AsyncSession, team_id: str, user_id: str) -> TeamMember | None:
    return (
        await db.execute(select(TeamMember).where(TeamMember.team_id == team_id, TeamMember.user_id == user_id))
    ).scalar_one_or_none()


async def _require_team_manager(db: AsyncSession, team_id: str, actor: User) -> TeamMember | None:
    if await _is_global_admin(db, actor.id):
        return None
    membership = await _team_membership(db, team_id, actor.id)
    if membership is None or membership.role not in {"owner", "admin"}:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Team admin access required")
    return membership


def _serialize_team_payload(
    team: Team,
    *,
    membership: TeamMember | None,
    member_count: int,
    project_count: int,
) -> dict[str, object]:
    return {
        "id": team.id,
        "name": team.name,
        "description": team.description,
        "avatar_url": team.avatar_url,
        "created_by": team.created_by,
        "created_at": team.created_at.isoformat() if team.created_at else None,
        "my_role": membership.role if membership else None,
        "member_count": int(member_count or 0),
        "project_count": int(project_count or 0),
    }


async def _team_memberships_by_team_ids(
    db: AsyncSession,
    *,
    team_ids: Iterable[str],
    user_id: str,
) -> dict[str, TeamMember]:
    normalized_team_ids = [team_id for team_id in team_ids if str(team_id or "").strip()]
    if not normalized_team_ids:
        return {}
    rows = (
        (
            await db.execute(
                select(TeamMember).where(
                    TeamMember.user_id == user_id,
                    TeamMember.team_id.in_(normalized_team_ids),
                )
            )
        )
        .scalars()
        .all()
    )
    return {row.team_id: row for row in rows}


async def _team_member_counts_by_team_ids(db: AsyncSession, *, team_ids: Iterable[str]) -> dict[str, int]:
    normalized_team_ids = [team_id for team_id in team_ids if str(team_id or "").strip()]
    if not normalized_team_ids:
        return {}
    rows = (
        await db.execute(
            select(TeamMember.team_id, func.count())
            .where(TeamMember.team_id.in_(normalized_team_ids))
            .group_by(TeamMember.team_id)
        )
    ).all()
    return {team_id: int(member_count or 0) for team_id, member_count in rows}


async def _team_project_counts_by_team_ids(db: AsyncSession, *, team_ids: Iterable[str]) -> dict[str, int]:
    normalized_team_ids = [team_id for team_id in team_ids if str(team_id or "").strip()]
    if not normalized_team_ids:
        return {}
    rows = (
        await db.execute(
            select(TeamProject.team_id, func.count())
            .where(TeamProject.team_id.in_(normalized_team_ids))
            .group_by(TeamProject.team_id)
        )
    ).all()
    return {team_id: int(project_count or 0) for team_id, project_count in rows}


async def _serialize_team(db: AsyncSession, team: Team, current_user_id: str) -> dict:
    membership = await _team_membership(db, team.id, current_user_id)
    member_count = (
        await db.execute(select(func.count()).select_from(TeamMember).where(TeamMember.team_id == team.id))
    ).scalar_one()
    project_count = (
        await db.execute(select(func.count()).select_from(TeamProject).where(TeamProject.team_id == team.id))
    ).scalar_one()
    return _serialize_team_payload(
        team,
        membership=membership,
        member_count=int(member_count or 0),
        project_count=int(project_count or 0),
    )


async def list_teams(db: AsyncSession, current_user: User) -> list[dict]:
    stmt = select(Team).order_by(Team.name.asc())
    if not await _is_global_admin(db, current_user.id):
        stmt = stmt.join(TeamMember, TeamMember.team_id == Team.id).where(TeamMember.user_id == current_user.id)
    teams = (await db.execute(stmt)).scalars().all()
    team_ids = [team.id for team in teams]
    memberships = await _team_memberships_by_team_ids(db, team_ids=team_ids, user_id=current_user.id)
    member_counts = await _team_member_counts_by_team_ids(db, team_ids=team_ids)
    project_counts = await _team_project_counts_by_team_ids(db, team_ids=team_ids)
    return [
        _serialize_team_payload(
            team,
            membership=memberships.get(team.id),
            member_count=member_counts.get(team.id, 0),
            project_count=project_counts.get(team.id, 0),
        )
        for team in teams
    ]


async def create_team(
    db: AsyncSession,
    *,
    current_user: User,
    name: str,
    description: str | None,
    avatar_url: str | None,
) -> dict:
    if (await db.execute(select(Team).where(func.lower(Team.name) == name.strip().lower()))).scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Team name already exists")
    team = Team(
        id=str(uuid.uuid4()),
        name=name.strip(),
        description=(description or "").strip() or None,
        avatar_url=(avatar_url or "").strip() or None,
        created_by=current_user.id,
    )
    db.add(team)
    db.add(TeamMember(team_id=team.id, user_id=current_user.id, role="owner", added_by=current_user.id))
    await db.commit()
    await db.refresh(team)
    return await _serialize_team(db, team, current_user.id)


async def add_team_member(
    db: AsyncSession,
    *,
    team_id: str,
    current_user: User,
    user_id: str,
    role: str,
) -> dict:
    team = await db.get(Team, team_id)
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")
    await _require_team_manager(db, team_id, current_user)
    normalized_role = role.strip().lower()
    if normalized_role not in TEAM_MEMBER_ROLES:
        raise HTTPException(status_code=400, detail="Invalid team role")
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    membership = await _team_membership(db, team_id, user_id)
    if membership is None:
        membership = TeamMember(team_id=team_id, user_id=user_id, role=normalized_role, added_by=current_user.id)
        db.add(membership)
    else:
        membership.role = normalized_role
        membership.added_by = current_user.id
    await db.flush()
    await create_notification(
        db,
        user_id=user.id,
        notification_type="team.member_added",
        title=f"Added to team {team.name}",
        body=f"You were added to team '{team.name}' as {normalized_role}.",
    )
    await db.commit()
    return await _serialize_team(db, team, current_user.id)


async def grant_team_project(
    db: AsyncSession,
    *,
    team_id: str,
    current_user: User,
    project_id: str,
    role: str,
) -> dict:
    team = await db.get(Team, team_id)
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")
    project = await db.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    await _require_team_manager(db, team_id, current_user)
    if not await _is_global_admin(db, current_user.id):
        user_project = (
            await db.execute(
                select(UserProject).where(UserProject.project_id == project_id, UserProject.user_id == current_user.id)
            )
        ).scalar_one_or_none()
        if user_project is None:
            raise HTTPException(status_code=403, detail="Project access required to grant team access")
    normalized_role = role.strip().lower()
    if normalized_role not in TEAM_MEMBER_ROLES:
        raise HTTPException(status_code=400, detail="Invalid project role")
    team_project = (
        await db.execute(
            select(TeamProject).where(TeamProject.team_id == team_id, TeamProject.project_id == project_id)
        )
    ).scalar_one_or_none()
    if team_project is None:
        team_project = TeamProject(
            team_id=team_id,
            project_id=project_id,
            role=normalized_role,
            granted_by=current_user.id,
        )
        db.add(team_project)
    else:
        team_project.role = normalized_role
        team_project.granted_by = current_user.id
    await db.commit()
    return await _serialize_team(db, team, current_user.id)


async def _notification_preferences(db: AsyncSession, user_id: str) -> NotificationPreference:
    pref = await db.get(NotificationPreference, user_id)
    if pref is None:
        pref = NotificationPreference(user_id=user_id)
        db.add(pref)
        await db.flush()
    return pref


async def list_notifications(
    db: AsyncSession,
    *,
    current_user: User,
    unread_only: bool = False,
    limit: int = 50,
) -> list[dict]:
    stmt = (
        select(Notification)
        .where(Notification.user_id == current_user.id)
        .order_by(Notification.created_at.desc())
        .limit(max(1, min(limit, 200)))
    )
    if unread_only:
        stmt = stmt.where(not Notification.is_read)
    rows = (await db.execute(stmt)).scalars().all()
    return [
        {
            "id": row.id,
            "type": row.type,
            "title": row.title,
            "body": row.body,
            "link": row.link,
            "is_read": bool(row.is_read),
            "created_at": row.created_at.isoformat() if row.created_at else None,
            "read_at": row.read_at.isoformat() if row.read_at else None,
        }
        for row in rows
    ]


async def mark_notification_read(
    db: AsyncSession,
    *,
    notification_id: str,
    current_user: User,
) -> dict:
    notification = await db.get(Notification, notification_id)
    if not notification or notification.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Notification not found")
    notification.is_read = True
    notification.read_at = utc_now()
    await db.commit()
    return {
        "id": notification.id,
        "type": notification.type,
        "title": notification.title,
        "body": notification.body,
        "link": notification.link,
        "is_read": True,
        "created_at": notification.created_at.isoformat() if notification.created_at else None,
        "read_at": notification.read_at.isoformat() if notification.read_at else None,
    }


async def get_notification_preferences(db: AsyncSession, current_user: User) -> dict:
    pref = await _notification_preferences(db, current_user.id)
    await db.commit()
    return _preference_view(pref)


def _preference_view(pref) -> dict:
    return {
        "user_id": pref.user_id,
        "in_app_enabled": bool(pref.in_app_enabled),
        "email_enabled": bool(pref.email_enabled),
        "slack_enabled": bool(pref.slack_enabled),
        "teams_enabled": bool(pref.teams_enabled),
        "quiet_hours": dict(pref.quiet_hours) if isinstance(pref.quiet_hours, dict) else None,
    }


async def update_notification_preferences(
    db: AsyncSession,
    *,
    current_user: User,
    in_app_enabled: bool | None = None,
    email_enabled: bool | None = None,
    slack_enabled: bool | None = None,
    teams_enabled: bool | None = None,
    quiet_hours: dict | None = None,
) -> dict:
    """A partial update: ``None`` keeps the stored value (the companion sends only its quiet hours)."""
    from ..attention.quiet_hours import normalize

    pref = await _notification_preferences(db, current_user.id)
    for name, value in (("in_app_enabled", in_app_enabled), ("email_enabled", email_enabled),
                        ("slack_enabled", slack_enabled), ("teams_enabled", teams_enabled)):
        if value is not None:
            setattr(pref, name, bool(value))
    if quiet_hours is not None:
        pref.quiet_hours = normalize(quiet_hours)
    await db.commit()
    return _preference_view(pref)


async def create_notification(
    db: AsyncSession,
    *,
    user_id: str,
    notification_type: str,
    title: str,
    body: str | None = None,
    link: str | None = None,
    payload: dict | None = None,
    project_id: str | None = None,
) -> Notification | None:
    pref = await _notification_preferences(db, user_id)
    notification: Notification | None = None
    if not pref.in_app_enabled:
        notification = None
    else:
        notification = Notification(
            id=str(uuid.uuid4()),
            user_id=user_id,
            type=notification_type,
            title=title,
            body=body,
            link=link,
        )
        db.add(notification)
        await db.flush()
    try:
        from ..notification_delivery import enqueue_outbound_notification_deliveries

        await enqueue_outbound_notification_deliveries(
            db,
            notification_id=notification.id if notification else None,
            user_id=user_id,
            notification_type=notification_type,
            title=title,
            body=body,
            link=link,
            payload=payload,
            project_id=project_id,
        )
    except Exception:
        pass
    return notification


async def notify_admins(
    db: AsyncSession,
    *,
    notification_type: str,
    title: str,
    body: str | None = None,
    link: str | None = None,
    payload: dict | None = None,
    project_id: str | None = None,
    exclude_user_id: str | None = None,
) -> None:
    rows = await db.execute(
        select(User.id)
        .join(UserRole, UserRole.user_id == User.id)
        .join(Role, Role.id == UserRole.role_id)
        .where(Role.name == "admin", User.is_active)
    )
    for (user_id,) in rows.all():
        if exclude_user_id and user_id == exclude_user_id:
            continue
        await create_notification(
            db,
            user_id=user_id,
            notification_type=notification_type,
            title=title,
            body=body,
            link=link,
        )
    if project_id:
        try:
            from ..notification_delivery import enqueue_project_notification_deliveries

            await enqueue_project_notification_deliveries(
                db,
                notification_type=notification_type,
                title=title,
                body=body,
                link=link,
                payload=payload,
                project_id=project_id,
            )
        except Exception:
            pass
