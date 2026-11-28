from __future__ import annotations

import json

from sqlalchemy import select

from app.models import ChannelConfig, Project, SecretAccessAuditLog, StoredSecret, User
from app.plugins.channels.teams_plugin import TeamsPlugin
from app.services.channel_config import ChannelConfigService
from app.services.channel_config.credentials import (
    CHANNEL_SEND,
    CHANNEL_START,
    channel_runtime_config,
    channel_secret_scope,
)
from app.services.channel_config.secret_fields import mask_channel_config
from app.services.secret import get_secret_value
from app.tools.context import ToolContext
from app.tools.proactive_teams_impl import AskReporterViaTeams

PASSWORD = "Synthetic~Teams.Pass-QXZW21"
ROTATED = "Synthetic~Teams.Pass-QXZW22"
TEAMS_FIELDS = [{"name": "app_password", "secret": True}, {"name": "app_id"}]


async def _workspaces(db) -> tuple[Project, Project]:
    rows = (await db.execute(select(Project).where(Project.name.in_(("acme-orders", "acme-billing"))))).scalars()
    found = {row.name: row for row in rows}
    if "acme-billing" not in found:
        found["acme-billing"] = Project(name="acme-billing", source_type="local", is_system=False)
        db.add(found["acme-billing"])
        await db.flush()
    return found["acme-orders"], found["acme-billing"]


async def _teams(db, project_id: str) -> ChannelConfig:
    created = await ChannelConfigService.create(db, plugin_id="msteams", name="audited-teams", project_id=project_id,
                                                enabled=True, config={"app_id": "app-0021", "app_password": PASSWORD})
    return await db.get(ChannelConfig, created.id)


async def _channel_secrets(db, channel_id: int) -> list[StoredSecret]:
    return list((await db.execute(select(StoredSecret).where(
        StoredSecret.tool_name == channel_secret_scope(channel_id)))).scalars())


async def test_a_created_channel_keeps_only_a_reference_to_its_stored_secret(db):
    workspace, _other = await _workspaces(db)
    channel = await _teams(db, workspace.id)
    config = json.loads(channel.config)
    assert PASSWORD not in channel.config and set(config) == {"app_id", "app_password_secret_ref"}
    [secret] = await _channel_secrets(db, channel.id)
    assert (secret.id, secret.field_name, secret.project_id) == (config["app_password_secret_ref"], "app_password",
                                                                 workspace.id)
    assert mask_channel_config(config, TEAMS_FIELDS) == ({"app_id": "app-0021"},
                                                         {"app_password": {"has_value": True}})


async def test_an_update_keeps_an_omitted_secret_rotates_a_sent_one_and_ignores_a_sent_reference(db):
    workspace, _other = await _workspaces(db)
    channel = await _teams(db, workspace.id)
    ref = json.loads(channel.config)["app_password_secret_ref"]
    await ChannelConfigService.update(db, channel.id, config={"app_id": "app-0022", "app_password": "",
                                                              "app_password_secret_ref": "secret-of-someone-else"})
    await db.refresh(channel)
    assert json.loads(channel.config) == {"app_id": "app-0022", "app_password_secret_ref": ref}
    await ChannelConfigService.update(db, channel.id, config={"app_id": "app-0022", "app_password": ROTATED})
    await db.refresh(channel)
    assert json.loads(channel.config)["app_password_secret_ref"] == ref and ROTATED not in channel.config
    assert await get_secret_value(db, secret_id=ref, purpose="test.read") == ROTATED


async def test_a_started_plugin_gets_the_value_through_the_audited_choke_point(db):
    workspace, _other = await _workspaces(db)
    channel = await _teams(db, workspace.id)
    plugin = TeamsPlugin(str(channel.id), await channel_runtime_config(db, channel, purpose=CHANNEL_START))
    assert plugin.app_password == PASSWORD
    ref = json.loads(channel.config)["app_password_secret_ref"]
    [row] = (await db.execute(select(SecretAccessAuditLog).where(SecretAccessAuditLog.secret_id == ref))).scalars()
    assert (row.purpose, row.project_id) == (CHANNEL_START, workspace.id)


async def test_a_channel_moved_to_another_workspace_takes_its_secret_along_and_still_starts(db):
    workspace, other = await _workspaces(db)
    channel = await _teams(db, workspace.id)
    await ChannelConfigService.update(db, channel.id, project_id=other.id)
    await db.refresh(channel)
    [secret] = await _channel_secrets(db, channel.id)
    assert secret.project_id == other.id
    assert (await channel_runtime_config(db, channel, purpose=CHANNEL_START))["app_password"] == PASSWORD


async def test_deleting_a_channel_releases_its_stored_secrets(db):
    workspace, _other = await _workspaces(db)
    channel = await _teams(db, workspace.id)
    channel_id = channel.id
    assert await ChannelConfigService.delete(db, channel_id)
    assert await _channel_secrets(db, channel_id) == []


async def test_the_proactive_teams_tool_reads_the_password_for_sending(db, monkeypatch):
    workspace, _other = await _workspaces(db)
    channel = await _teams(db, workspace.id)
    used: list[str] = []

    async def send(self, email, message):
        used.append(self.app_password)
        return None

    monkeypatch.setattr("app.services.proactive_teams.proactive_teams_service.ProactiveTeamsService."
                        "send_proactive_message", send)
    monkeypatch.setattr("app.tools.proactive_teams_impl.outbound_message_refusal", lambda *_args: None)
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    context = ToolContext(user_id=admin.id, project_ids=[workspace.id], roles=["admin"], session_id="session-0021",
                          project_config={}, db=db)
    await AskReporterViaTeams().execute(
        {"ticket_id": "OCX-104", "reporter_email": "reporter@example.com", "question": "Which build?"}, context)
    assert used == [PASSWORD]
    ref = json.loads(channel.config)["app_password_secret_ref"]
    purposes = (await db.execute(select(SecretAccessAuditLog.purpose).where(
        SecretAccessAuditLog.secret_id == ref))).scalars().all()
    assert CHANNEL_SEND in purposes
