"""Contract: a Teams call's chat session is owned like a channel chat message."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.models import Project, Session, User
from app.plugins import plugin_manager
from app.plugins.channels.teams_plugin import TeamsPlugin
from app.services.channel_config import ChannelConfigService
from app.services.channel_config.service_user import deactivate_channel_service_user, service_username
from app.services.teams_calling.call_session_state import cleanup_call_state, ensure_call_db_session


async def _call_session(db, channel_id: str, project_id: str, caller_id: str):
    call_id = f"call-{uuid.uuid4().hex[:8]}"
    try:
        result = await ensure_call_db_session(call_id, project_id, channel_id, db, caller_id=caller_id)
    finally:
        cleanup_call_state(call_id)
    owner = None
    if result.session_id:
        owner = (await db.execute(select(Session.user_id).where(Session.id == result.session_id))).scalar_one()
    return result.state, owner


@pytest.mark.asyncio
async def test_a_call_session_is_owned_by_the_mapped_caller_or_the_channel_service_user(db, monkeypatch):
    project = (await db.execute(select(Project).where(Project.name == "acme-orders"))).scalar_one()
    channel = await ChannelConfigService.create(
        db, plugin_id="msteams", name="Calls", project_id=project.id, enabled=False, config={}
    )
    channel_id = str(channel.id)
    mapped = User(
        id=str(uuid.uuid4()),
        username=f"caller-{uuid.uuid4().hex[:6]}",
        email=f"caller-{uuid.uuid4().hex[:6]}@example.test",
        password_hash="not-a-login",
        is_active=True,
    )
    db.add(mapped)
    await db.flush()
    plugin = TeamsPlugin("msteams", {"__channel_id": channel_id, "sender_mappings": {"aad-mapped": mapped.id}})
    monkeypatch.setitem(plugin_manager._plugins, channel_id, plugin)
    service_user = (await db.execute(select(User).where(User.username == service_username(channel.id)))).scalar_one()
    first_user = (await db.execute(select(User).limit(1))).scalar_one()
    assert first_user.id != service_user.id

    assert await _call_session(db, channel_id, project.id, "aad-mapped") == (None, mapped.id)
    assert await _call_session(db, channel_id, project.id, "aad-unmapped") == (None, service_user.id)
    assert await _call_session(db, channel_id, project.id, "") == (None, service_user.id)

    plugin.require_registered_user = True
    assert await _call_session(db, channel_id, project.id, "aad-unmapped") == ("channel_sender_unresolved", None)
    plugin.require_registered_user = False

    await deactivate_channel_service_user(db, channel.id)
    sessions_before = len((await db.execute(select(Session.id))).all())
    assert await _call_session(db, channel_id, project.id, "aad-unmapped") == (
        "channel_service_user_not_configured",
        None,
    )
    assert len((await db.execute(select(Session.id))).all()) == sessions_before

    monkeypatch.delitem(plugin_manager._plugins, channel_id)
    assert await _call_session(db, channel_id, project.id, "aad-mapped") == ("call_channel_not_active", None)
