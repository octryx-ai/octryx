import uuid

import pytest
from sqlalchemy import select

from app.models import Project, Team, TeamMember, TeamProject, User
from app.services.team_notification import list_teams


@pytest.mark.asyncio
async def test_list_teams_preserves_counts_and_membership_for_admin(db):
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    project = (await db.execute(select(Project).order_by(Project.name.asc()))).scalars().first()
    assert project is not None

    team_a = Team(id=str(uuid.uuid4()), name="Alpha Team", created_by=admin.id)
    team_b = Team(id=str(uuid.uuid4()), name="Beta Team", created_by=admin.id)
    db.add_all(
        [
            team_a,
            team_b,
            TeamMember(team_id=team_a.id, user_id=admin.id, role="owner", added_by=admin.id),
            TeamMember(team_id=team_b.id, user_id=admin.id, role="admin", added_by=admin.id),
            TeamProject(team_id=team_a.id, project_id=project.id, role="member", granted_by=admin.id),
        ]
    )
    await db.commit()

    payload = await list_teams(db, admin)

    assert [row["name"] for row in payload] == ["Alpha Team", "Beta Team"]
    alpha = next(row for row in payload if row["id"] == team_a.id)
    beta = next(row for row in payload if row["id"] == team_b.id)

    assert alpha["my_role"] == "owner"
    assert alpha["member_count"] == 1
    assert alpha["project_count"] == 1
    assert beta["my_role"] == "admin"
    assert beta["member_count"] == 1
    assert beta["project_count"] == 0


@pytest.mark.asyncio
async def test_list_teams_filters_to_member_scope_for_non_admin(db):
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    member = User(
        id=str(uuid.uuid4()),
        username="team-member",
        email="team-member@example.com",
        password_hash="hash",
        is_active=True,
    )
    db.add(member)

    visible_team = Team(id=str(uuid.uuid4()), name="Visible Team", created_by=admin.id)
    hidden_team = Team(id=str(uuid.uuid4()), name="Hidden Team", created_by=admin.id)
    db.add_all(
        [
            visible_team,
            hidden_team,
            TeamMember(team_id=visible_team.id, user_id=member.id, role="viewer", added_by=admin.id),
            TeamMember(team_id=visible_team.id, user_id=admin.id, role="owner", added_by=admin.id),
            TeamMember(team_id=hidden_team.id, user_id=admin.id, role="owner", added_by=admin.id),
        ]
    )
    await db.commit()

    payload = await list_teams(db, member)

    assert len(payload) == 1
    assert payload[0]["id"] == visible_team.id
    assert payload[0]["my_role"] == "viewer"
    assert payload[0]["member_count"] == 2
    assert payload[0]["project_count"] == 0
