import json

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.models import ChannelConfig, Project
from app.services.teams_calling.channel_context import get_channel_calling_context


async def _first_project_id(db) -> str:
    project = (await db.execute(select(Project).limit(1))).scalar_one()
    return str(project.id)


@pytest.mark.asyncio
async def test_get_channel_calling_context_accepts_enabled_teams_channel(db):
    project_id = await _first_project_id(db)
    channel = ChannelConfig(
        plugin_id="msteams",
        name="Teams Calling",
        project_id=project_id,
        enabled=True,
        config=json.dumps({"calling_enabled": True}),
    )
    db.add(channel)
    await db.commit()
    await db.refresh(channel)

    context = await get_channel_calling_context(db, channel_id=str(channel.id), project_id=project_id)

    assert context.channel_id == str(channel.id)
    assert context.project_id == project_id
    assert context.config == {"calling_enabled": True}


@pytest.mark.asyncio
async def test_a_channel_bound_to_another_workspace_is_not_found(db):
    project_id = await _first_project_id(db)
    channel = ChannelConfig(
        plugin_id="msteams",
        name="Teams Calling",
        project_id=project_id,
        enabled=True,
        config=json.dumps({"calling_enabled": True}),
    )
    db.add(channel)
    await db.commit()
    await db.refresh(channel)

    with pytest.raises(HTTPException) as exc_info:
        await get_channel_calling_context(db, channel_id=str(channel.id), project_id="other-project")

    assert (exc_info.value.status_code, exc_info.value.detail) == (404, "Channel not found")


@pytest.mark.asyncio
async def test_get_channel_calling_context_rejects_disabled_calling(db):
    project_id = await _first_project_id(db)
    channel = ChannelConfig(
        plugin_id="msteams",
        name="Teams Calling",
        project_id=project_id,
        enabled=True,
        config=json.dumps({"calling_enabled": False}),
    )
    db.add(channel)
    await db.commit()
    await db.refresh(channel)

    with pytest.raises(HTTPException) as exc_info:
        await get_channel_calling_context(db, channel_id=str(channel.id), project_id=project_id)

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == "Calling not enabled for this channel"


@pytest.mark.asyncio
async def test_get_channel_calling_context_rejects_non_integer_channel_id(db):
    with pytest.raises(HTTPException) as exc_info:
        await get_channel_calling_context(db, channel_id="not-an-id", project_id="project-1")

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "channel_id must be an integer"
