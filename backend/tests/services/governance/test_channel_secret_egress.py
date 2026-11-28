from __future__ import annotations

import io
import json
import logging
import zipfile

import httpx
import pytest
from sqlalchemy import select

from app.models import AuditLog, ChannelConfig, Project, User
from app.plugins import plugin_manager
from app.plugins.channels.telegram import TelegramPlugin
from app.services.channel_config import ChannelConfigService
from app.services.data_transfer.export_payloads import (
    _build_admin_config_backup_payload,
    _build_definition_export_payload,
)
from app.services.data_transfer.gdpr_export import _build_user_data_gdpr_zip
from app.services.observability.logging import configure_json_logging
from app.services.secret_masking import masked
from app.tools.admin_impl._admin_channels import (
    AdminCreateChannelTool,
    AdminListChannelsTool,
    AdminUpdateChannelTool,
)
from app.tools.context import ToolContext
from app.tools.proactive_teams_impl import AskReporterViaTeams
from tests.conftest import ADMIN_PASSWORD

# Synthetic values. The Slack token literal is split so secret scanners do not flag the fixture.
SECRETS = {
    "msteams": {"app_id": "app-0001", "app_password": "Synthetic~Teams.Pass-QXZW01"},
    "slack": {"bot_token": "xoxb-" "0000000001-0000000002-SyntheticSlackQXZW",
              "signing_secret": "synthetic-slack-signing-QXZW02"},
    "email": {"smtp_host": "mail.example.com", "smtp_password": "Synthetic~Smtp.Pass-QXZW03",
              "imap_password": "Synthetic~Imap.Pass-QXZW04"},
    "matrix": {"homeserver": "https://matrix.example.com", "password": "Synthetic~Matrix.Pass-QXZW05",
               "access_token": "synthetic-matrix-token-QXZW06"},
    "telegram": {"bot_token": "100000001:AAsyntheticTelegramBotTokenQXZW07"},
}
SECRET_VALUES = [value for config in SECRETS.values() for key, value in config.items()
                 if key not in ("app_id", "smtp_host", "homeserver")]


def assert_no_secret(text: object) -> None:
    serialized = text if isinstance(text, str) else json.dumps(text, default=str)
    for value in SECRET_VALUES:
        assert value not in serialized


async def _channels(db, project_id: str | None = None) -> dict[str, ChannelConfig]:
    rows = {}
    for plugin_id, config in SECRETS.items():
        created = await ChannelConfigService.create(db, plugin_id=plugin_id, name=f"egress-{plugin_id}",
                                                    project_id=project_id, enabled=False, config=config)
        rows[plugin_id] = await db.get(ChannelConfig, created.id)
    return rows


async def _admin(db) -> User:
    return (await db.execute(select(User).where(User.username == "admin"))).scalar_one()


async def _workspace(db) -> Project:
    return (await db.execute(select(Project).where(Project.name == "acme-orders"))).scalar_one()


def _admin_context(db, admin: User, project_id: str) -> ToolContext:
    return ToolContext(user_id=admin.id, project_ids=[project_id], roles=["admin"], session_id="session-0001",
                       project_config={}, db=db)


async def test_the_admin_panel_lists_and_details_no_channel_secret_of_any_plugin(client, db):
    rows = await _channels(db)
    assert (await client.post("/admin/login", data={"username": "admin", "password": ADMIN_PASSWORD})).status_code \
        == 303
    responses = [await client.get("/admin/chat/api/panel/channels"),
                 await client.get("/admin/chat/api/panel/channels/available")]
    responses += [await client.get(f"/admin/chat/api/panel/channels/{row.id}") for row in rows.values()]
    for response in responses:
        assert response.status_code == 200
        assert_no_secret(response.text)


async def test_the_workspace_channel_list_returns_no_channel_secret(client, db, auth_headers):
    workspace = await _workspace(db)
    for row in (await _channels(db, workspace.id)).values():
        row.enabled = True
    await db.commit()
    response = await client.get("/api/v1/channels", params={"project_id": workspace.id}, headers=auth_headers)
    assert response.status_code == 200 and response.json()["count"] >= len(SECRETS)
    assert_no_secret(response.text)


async def test_panel_saves_and_reloads_write_no_channel_secret_to_responses_or_audit(admin_client, db, monkeypatch):
    async def failing_reload(_channel_id, _plugin_id, config):
        raise RuntimeError(f"start failed with {json.dumps(config)}")

    monkeypatch.setattr(plugin_manager, "reload_channel", failing_reload)
    answers = []
    for plugin_id, config in SECRETS.items():
        created = await admin_client.post("/admin/chat/api/panel/channels",
                                    json={"plugin_id": plugin_id, "name": f"saved-{plugin_id}", "enabled": True,
                                          "config": config})
        channel_id = created.json()["id"]
        answers += [created, await admin_client.put(f"/admin/chat/api/panel/channels/{channel_id}",
                                              json={"enabled": True, "config": config}),
                    await admin_client.post(f"/admin/chat/api/panel/channels/{channel_id}/reload")]
    assert {answer.status_code for answer in answers} <= {200, 500}
    for answer in answers:
        assert_no_secret(answer.text)
    audit = (await db.execute(select(AuditLog).where(AuditLog.resource_type.in_(("channel_plugin", "api"))))).scalars()
    assert_no_secret([[row.action, row.resource_id, row.details] for row in audit])


async def test_the_admin_channel_tools_return_no_channel_secret_even_when_a_start_fails(db, monkeypatch):
    admin, workspace = await _admin(db), await _workspace(db)
    context = _admin_context(db, admin, workspace.id)

    async def failing_reload(_channel_id, _plugin_id, config):
        raise RuntimeError(f"start failed with {json.dumps(config)}")

    monkeypatch.setattr(plugin_manager, "reload_channel", failing_reload)
    outputs = []
    for plugin_id, config in SECRETS.items():
        created = await AdminCreateChannelTool().execute(
            {"plugin_id": plugin_id, "name": f"tool-{plugin_id}", "config": config}, context)
        outputs += [created, await AdminUpdateChannelTool().execute(
            {"channel_id": str(created["channel"]["id"]), "merge_config": config, "enabled": True}, context)]
    outputs.append(await AdminListChannelsTool().execute({}, context))
    assert all("error" not in output for output in outputs), outputs
    assert "error: " in outputs[0]["channel"]["status"]
    assert_no_secret(outputs)


def test_a_channel_tool_call_input_is_stored_masked():
    stored = masked({"plugin_id": "telegram", "config": SECRETS["telegram"],
                     "merge_config": {**SECRETS["msteams"], **SECRETS["slack"], **SECRETS["email"],
                                      **SECRETS["matrix"]}})
    assert_no_secret(stored)


async def test_workspace_definition_and_user_exports_carry_no_channel_secret(db):
    admin, workspace = await _admin(db), await _workspace(db)
    await _channels(db, workspace.id)
    assert_no_secret(await _build_admin_config_backup_payload(db, project_id=workspace.id))
    for export_type in ("task_definitions", "agent_definitions"):
        assert_no_secret(await _build_definition_export_payload(db, export_type=export_type, project_id=workspace.id))
    archive = zipfile.ZipFile(io.BytesIO(await _build_user_data_gdpr_zip(db, user_id=admin.id)))
    assert_no_secret("".join(archive.read(name).decode("utf-8", "replace") for name in archive.namelist()))


async def test_the_proactive_teams_tool_answers_without_the_bot_password(db, monkeypatch):
    admin, workspace = await _admin(db), await _workspace(db)
    await ChannelConfigService.create(db, plugin_id="msteams", name="egress-proactive", project_id=workspace.id,
                                      enabled=True, config=SECRETS["msteams"])

    async def unreachable(self, email, message):
        return None

    monkeypatch.setattr("app.services.proactive_teams.proactive_teams_service.ProactiveTeamsService."
                        "send_proactive_message", unreachable)
    monkeypatch.setattr("app.tools.proactive_teams_impl.outbound_message_refusal", lambda *_args: None)
    context = _admin_context(db, admin, workspace.id)
    output = await AskReporterViaTeams().execute(
        {"ticket_id": "OCX-103", "reporter_email": "reporter@example.com", "question": "Which build?"}, context)
    assert "Could not reach reporter" in output["error"]
    assert_no_secret(output)


async def test_a_telegram_start_failure_names_neither_the_token_nor_its_url(monkeypatch, caplog):
    token = SECRETS["telegram"]["bot_token"]

    async def refused(self, url, **_kwargs):
        response = httpx.Response(401, request=httpx.Request("GET", url))
        response.raise_for_status()

    monkeypatch.setattr(httpx.AsyncClient, "get", refused)
    plugin = TelegramPlugin("telegram", {"bot_token": token, "enabled": True})
    with caplog.at_level(logging.DEBUG), pytest.raises(RuntimeError) as refused_start:
        await plugin.initialize()
    assert token not in str(refused_start.value) and refused_start.value.__cause__ is None
    assert_no_secret(caplog.text)


def test_request_urls_of_httpx_stay_out_of_the_info_log():
    configure_json_logging()
    assert not logging.getLogger("httpx").isEnabledFor(logging.INFO)
