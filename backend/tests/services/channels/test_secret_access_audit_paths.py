from __future__ import annotations

import time
import uuid
from types import SimpleNamespace

import httpx
import pytest
from sqlalchemy import select

from app.models import (
    BuiltInToolConfig,
    ConnectorWatcher,
    DatabaseConnector,
    IdentityProvider,
    LLMProvider,
    RepositoryGitToken,
    RestApiConnection,
    Webhook,
)
from app.services.confluence_pages.tree_connection import _global_base
from app.services.connector_health.service import refresh_all_connector_health
from app.services.connector_watcher_service.watchers import _verify_webhook_secret
from app.services.control_plane_service import build_provider_client_kwargs_async, resolve_provider_api_key
from app.services.data_access import as_viewer
from app.services.database_tool.connector_engine import resolve_connector_config
from app.services.design_delivery_sync.scm_common import resolved_gitlab_config
from app.services.github_connector.service import _resolved_github_config
from app.services.inbound_alerts.signature import sign_timestamped
from app.services.inbound_alerts.trigger import verify_signature
from app.services.knowledge.sources.repository_access import RepositoryIdentity
from app.services.knowledge.sources.repository_git_token import (
    SECRET_TOOL_NAME,
    repository_key,
    usable_git_token,
)
from app.services.mcp_server_registry_config import resolved_runtime_config, secret_tool_name
from app.services.named_connections.contract import NamedConnection, named_secret_field
from app.services.named_connections.store import resolved_config as named_connection_config
from app.services.oidc.provider_http import _provider_client_secret
from app.services.outbound_webhook import (
    create_outbound_webhook,
    emit_outbound_webhook_event,
    process_outbound_webhook_delivery_batch,
)
from app.services.rest_connector.common import secret_scope
from app.services.rest_connector.connections import resolved_config as rest_connection_config
from app.services.stt.service import _stt_setting
from app.services.tool_config import _project_config_for_tool_entry
from app.services.tts.service import (
    TTSConfig,
    TTSProviderConfig,
    is_tts_provider_available,
    load_tts_config,
    save_tts_config,
)
from app.tools.connectors.credential_boundary import connector_secret_value
from app.tools.context import ToolContext
from tests.support.secret_access_audit_support import (
    VALUE,
    assert_holds_no_value,
    assert_read_once,
    owner_and_workspace,
    reads_of,
    stored,
)


@pytest.fixture
async def owner_workspace(db):
    return await owner_and_workspace(db)


async def test_a_workspace_connector_config_records_its_read(db, owner_workspace):
    owner, workspace = owner_workspace
    secret = await stored(db, tool_name="jira", field_name="jira_token", project_id=workspace.id)
    entry = BuiltInToolConfig(tool_name="jira", project_id=workspace.id, config={"jira_token_secret_ref": secret.id})
    with as_viewer(owner.id):
        assert (await _project_config_for_tool_entry(db, entry))["jira_token"] == VALUE
    await assert_read_once(db, secret_id=secret.id, purpose="connector.workspace_config", workspace_id=workspace.id,
                           user=owner)


async def test_a_connector_tool_call_records_its_read(db, owner_workspace):
    owner, workspace = owner_workspace
    secret = await stored(db, tool_name="github", field_name="github_token", project_id=None)
    context = ToolContext(user_id=owner.id, project_ids=[workspace.id], roles=[], session_id="session-0001",
                          project_config={"github_token_secret_ref": secret.id}, db=db)
    with as_viewer(owner.id):
        assert await connector_secret_value(context, connector_name="github", field_name="github_token") == VALUE
    await assert_read_once(db, secret_id=secret.id, purpose="connector.tool_call", workspace_id=None, user=owner)


async def test_a_named_connection_records_its_read(db, owner_workspace):
    owner, workspace = owner_workspace
    connection_id = str(uuid.uuid4())
    secret = await stored(db, tool_name="github", field_name=named_secret_field("github_token", connection_id),
                          project_id=workspace.id)
    connection = NamedConnection(id=connection_id, tool_name="github", project_id=workspace.id, name="demo-shop",
                                 config={"github_token_secret_ref": secret.id})
    with as_viewer(owner.id):
        assert (await named_connection_config(db, connection))["github_token"] == VALUE
    await assert_read_once(db, secret_id=secret.id, purpose="named_connection.call", workspace_id=workspace.id,
                           user=owner)


async def test_a_rest_connection_records_its_read(db, owner_workspace):
    owner, workspace = owner_workspace
    connection = RestApiConnection(id=str(uuid.uuid4()), project_id=workspace.id)
    secret = await stored(db, tool_name=secret_scope(connection.id), field_name="api_key", project_id=workspace.id)
    connection.config = {"api_key_secret_ref": secret.id}
    with as_viewer(owner.id):
        assert (await rest_connection_config(db, connection))["api_key"] == VALUE
    await assert_read_once(db, secret_id=secret.id, purpose="rest_connector.call", workspace_id=workspace.id,
                           user=owner)


async def test_a_database_connector_records_its_read(db, owner_workspace):
    owner, workspace = owner_workspace
    scope = f"database_connector:{uuid.uuid4()}"
    secret = await stored(db, tool_name=scope, field_name="password", project_id=workspace.id)
    connector = DatabaseConnector(project_id=workspace.id, connection_config={"password_secret_ref": secret.id})
    with as_viewer(owner.id):
        assert (await resolve_connector_config(db, connector=connector, secret_scope=scope))["password"] == VALUE
    await assert_read_once(db, secret_id=secret.id, purpose="database_connector.query", workspace_id=workspace.id,
                           user=owner)


async def test_a_provider_api_key_records_its_read(db, owner_workspace):
    owner, _workspace = owner_workspace
    secret = await stored(db, tool_name="control_plane_provider:demo", field_name="api_key", project_id=None)
    provider = LLMProvider(id=str(uuid.uuid4()), name="demo-provider", api_key_secret_ref=secret.id)
    with as_viewer(owner.id):
        assert await resolve_provider_api_key(db, provider) == VALUE
    await assert_read_once(db, secret_id=secret.id, purpose="provider.credential", workspace_id=None, user=owner)


async def test_a_gateway_virtual_key_for_a_model_call_records_its_read(db, owner_workspace):
    owner, _workspace = owner_workspace
    secret = await stored(db, tool_name="control_plane_provider:gateway", field_name="api_key", project_id=None)
    provider = LLMProvider(id=str(uuid.uuid4()), name="demo-gateway", driver="litellm_gateway",
                           endpoint_url="https://gateway.example.com", api_key_secret_ref=secret.id)
    with as_viewer(owner.id):
        await build_provider_client_kwargs_async(db, provider)
    await assert_read_once(db, secret_id=secret.id, purpose="provider.credential", workspace_id=None, user=owner)


async def test_an_inbound_webhook_signature_check_records_its_read(db, owner_workspace):
    owner, workspace = owner_workspace
    secret = await stored(db, tool_name="webhook:demo", field_name="secret", project_id=workspace.id)
    webhook = Webhook(id=str(uuid.uuid4()), project_id=workspace.id, secret_ref=secret.id, accept_untimestamped=False)
    body, timestamp = b'{"alert": "INC0000101"}', str(int(time.time()))
    headers = {"X-Webhook-Timestamp": timestamp, "X-Webhook-Signature": sign_timestamped(VALUE, timestamp, body)}
    with as_viewer(owner.id):
        assert (await verify_signature(db, webhook, body, headers)).ok
    await assert_read_once(db, secret_id=secret.id, purpose="inbound_webhook.verify_signature",
                           workspace_id=workspace.id, user=owner)


async def test_a_connector_watcher_webhook_check_records_its_read(db, owner_workspace):
    owner, workspace = owner_workspace
    secret = await stored(db, tool_name="connector_watcher:demo", field_name="secret", project_id=workspace.id)
    watcher = ConnectorWatcher(project_id=workspace.id, secret_ref=secret.id, webhook_json={})
    with as_viewer(owner.id):
        await _verify_webhook_secret(db, watcher, VALUE)
    await assert_read_once(db, secret_id=secret.id, purpose="connector_watcher.verify_webhook",
                           workspace_id=workspace.id, user=owner)


async def test_an_oidc_sign_in_records_the_client_secret_read_as_anonymous(db):
    secret = await stored(db, tool_name="oidc:demo", field_name="client_secret", project_id=None)
    with as_viewer(None):
        assert await _provider_client_secret(db, IdentityProvider(client_secret_secret_ref=secret.id)) == VALUE
    row = await assert_read_once(db, secret_id=secret.id, purpose="oidc.sign_in", workspace_id=None)
    assert (row.principal, row.actor_user_id) == ("anonymous", None)


async def test_a_repository_git_token_records_its_read(db, owner_workspace):
    owner, workspace = owner_workspace
    repository = RepositoryIdentity(base="https://git.example.com", path="demo-shop/orders")
    row = RepositoryGitToken(id=str(uuid.uuid4()), project_id=workspace.id, host_base=repository.base,
                             repository_key=repository_key(repository))
    secret = await stored(db, tool_name=SECRET_TOOL_NAME, field_name=f"git_token:{row.id}", project_id=workspace.id)
    row.secret_id = secret.id
    db.add(row)
    await db.flush()
    with as_viewer(owner.id):
        assert await usable_git_token(db, workspace.id, repository) == VALUE
    await assert_read_once(db, secret_id=secret.id, purpose="knowledge.repository_git_token",
                           workspace_id=workspace.id, user=owner)


async def test_an_mcp_server_launch_records_its_read(db, owner_workspace):
    owner, workspace = owner_workspace
    secret = await stored(db, tool_name=secret_tool_name("demo-mcp"), field_name="token", project_id=workspace.id)
    binding = SimpleNamespace(secret_id=secret.id, field_name="token", target_kind="env", target_name="DEMO_TOKEN",
                              target_aliases_json=[])
    registration = SimpleNamespace(
        id="mcp-0001", name="demo-mcp", catalog_slug="demo", settings_json={}, secret_bindings=[binding],
        workspace_id=workspace.id, command="demo-mcp", args_json=[], transport="stdio", url=None, auto_start=False,
        description="")
    with as_viewer(owner.id):
        config = await resolved_runtime_config(db, registration=registration, catalog={"demo": {"fields": []}})
    assert config.env == {"DEMO_TOKEN": VALUE}
    await assert_read_once(db, secret_id=secret.id, purpose="mcp_server.launch", workspace_id=workspace.id,
                           user=owner)


@pytest.mark.parametrize(("tool_name", "field_name", "resolve", "purpose"), [
    ("gitlab", "gitlab_token", resolved_gitlab_config, "design_delivery.scm_sync"),
    ("github", "github_token", _resolved_github_config, "connector.github"),
    ("confluence", "confluence_api_token", _global_base, "confluence.page_tree"),
])
async def test_a_global_connector_config_records_its_read(db, owner_workspace, tool_name, field_name, resolve,
                                                           purpose):
    owner, _workspace = owner_workspace
    secret = await stored(db, tool_name=tool_name, field_name=field_name, project_id=None)
    await _global_entry(db, tool_name, {f"{field_name}_secret_ref": secret.id})
    with as_viewer(owner.id):
        assert (await resolve(db))[field_name] == VALUE
    await assert_read_once(db, secret_id=secret.id, purpose=purpose, workspace_id=None, user=owner)


async def test_a_connector_health_check_records_its_read(db):
    secret = await stored(db, tool_name="sonarqube", field_name="sonarqube_token", project_id=None)
    await _global_entry(db, "sonarqube", {"sonarqube_token_secret_ref": secret.id})
    tested: list[str] = []

    async def run_connection_test(tool_name, config, **_kwargs):
        tested.append(config.get("sonarqube_token"))
        return {"ok": True, "summary": "reachable"}

    await refresh_all_connector_health(db, run_connection_test=run_connection_test, force=True)
    assert VALUE in tested
    row = await assert_read_once(db, secret_id=secret.id, purpose="connector.health_check", workspace_id=None)
    assert row.principal.startswith("platform:")


async def test_text_to_speech_settings_and_keys_record_their_reads(db, owner_workspace):
    owner, _workspace = owner_workspace
    key = await stored(db, tool_name="tts", field_name="openai_api_key", project_id=None)
    with as_viewer(owner.id):
        await save_tts_config(db, TTSConfig(enabled=False))
        assert (await load_tts_config(db)).enabled is False
        assert await is_tts_provider_available(db, TTSProviderConfig(provider="openai"))
    await assert_read_once(db, secret_id=key.id, purpose="tts.provider_status", workspace_id=None, user=owner)
    [settings] = [row for row in await reads_of(db) if row.purpose == "tts.settings"]
    assert settings.principal == f"user:{owner.id}" and settings.secret_id


async def test_a_speech_to_text_setting_records_its_read(db, owner_workspace):
    owner, _workspace = owner_workspace
    secret = await stored(db, tool_name="stt", field_name="openai_api_key", project_id=None)
    with as_viewer(owner.id):
        assert await _stt_setting(db, "openai_api_key") == VALUE
    await assert_read_once(db, secret_id=secret.id, purpose="stt.transcription", workspace_id=None, user=owner)


async def test_an_outbound_webhook_delivery_records_the_signing_secret_read_on_its_webhook(db, monkeypatch, auth_user):
    created = await create_outbound_webhook(db, current_user=auth_user, payload={
        "name": "audited", "url": "https://hooks.example.com/in", "event_types": ["task.completed"]})
    await emit_outbound_webhook_event(db, event_type="task.completed", payload={"task_id": "OCX-102"})
    await db.commit()

    class Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_exc):
            return False

        async def post(self, url, **_kwargs):
            return httpx.Response(200, request=httpx.Request("POST", url))

    monkeypatch.setattr("app.services.outbound_webhook.httpx.AsyncClient", lambda *args, **kwargs: Client())
    assert await process_outbound_webhook_delivery_batch(db) == 1
    [row] = await reads_of(db, entity_id=created["id"])
    assert (row.secret_id, row.entity_type, row.purpose) == (None, "outbound_webhook", "outbound_webhook.sign")
    assert row.principal.startswith("platform:")
    assert_holds_no_value(row, created["signing_secret"])


async def _global_entry(db, tool_name: str, config: dict) -> None:
    entry = (await db.execute(select(BuiltInToolConfig).where(
        BuiltInToolConfig.tool_name == tool_name, BuiltInToolConfig.project_id.is_(None)))).scalar_one_or_none()
    if entry is None:
        entry = BuiltInToolConfig(tool_name=tool_name, project_id=None)
        db.add(entry)
    entry.config, entry.is_active = config, True
    await db.flush()
