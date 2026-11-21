"""``GET /api/v1/channels?project_id=`` lists a Workspace's channels only to its members.

The route needs an authenticated caller who belongs to the Workspace (a global admin sees any Workspace); without a
login it answers 401.
"""

from __future__ import annotations

import pytest

from app.models import ChannelConfig
from app.services.auth import create_access_token
from tests.agent_definition_revision_fixtures import make_member, make_project, make_user

pytestmark = pytest.mark.asyncio


def _headers(user) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user.id)}"}


async def test_channels_are_listed_only_to_members_of_the_workspace(client, db) -> None:
    project = await make_project(db)
    member = await make_user(db, label="member")
    outsider = await make_user(db, label="outsider")
    await make_member(db, member, project, "member")
    db.add(ChannelConfig(project_id=project.id, plugin_id="slack", name="ops", enabled=True, config="{}"))
    await db.commit()
    route = f"/api/v1/channels?project_id={project.id}"

    anonymous = await client.get(route)
    assert anonymous.status_code == 401
    assert "ops" not in anonymous.text

    refused = await client.get(route, headers=_headers(outsider))
    assert refused.status_code == 404  # the same answer as an unknown Workspace
    assert "ops" not in refused.text

    listed = await client.get(route, headers=_headers(member))
    assert listed.status_code == 200
    assert [channel["name"] for channel in listed.json()["channels"]] == ["ops"]
