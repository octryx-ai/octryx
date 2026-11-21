"""Contract: client credentials for ServiceNow (explicit mode, unchanged legacy order) and Source Sync;
secret rebind on a token URL or client id change, the credential unit, neutral presets, and no secret or token
in any log line or result. Stubs: ``oidc_stub_support.py``.
"""

from __future__ import annotations

import base64
import logging

import httpx
import pytest

import app.services.oidc_client_credentials as oidc
import app.services.oidc_token_cache as oidc_tokens
from app.services.atlassian_auth import request_auth
from app.services.atlassian_auth_modes import JIRA, AtlassianAuthConfigError
from app.services.atlassian_auth_validation import validate_auth_config
from app.services.knowledge.sources.sync.connections import SourceConnection
from app.services.knowledge.sources.sync.contract import (
    REASON_CONNECTION_NOT_CONFIGURED,
    REASON_EGRESS_REFUSED,
    REASON_SOURCE_CONTRACT_VIOLATION,
    REASON_SOURCE_UNAUTHORIZED,
    REASON_SOURCE_UNAVAILABLE,
    ConnectorError,
)
from app.services.knowledge.sources.sync.http import SourceReader
from app.services.knowledge.sources.sync.servicenow_connection import servicenow_connection
from app.services.servicenow_auth import resolve_servicenow_auth, validate_servicenow_auth_config
from app.services.tool_config.connection_fields import global_config_for_scope
from app.services.tool_config.presets import TOOL_CONFIG_PRESETS
from app.services.tool_config.secret_rebind import SecretRebindRequiredError, evaluate_secret_rebind
from tests.oidc_stub_support import (
    JIRA_URL,
    SECRET,
    SN_URL,
    _context,
    _jira,
    _priorities,
    _sn,
    stub_world,
)

# --- ServiceNow ------------------------------------------------------------------------------------------


@pytest.fixture
def world(monkeypatch):
    yield from stub_world(monkeypatch)


async def test_servicenow_tools_use_the_idp_token_and_retry_once(world):
    from app.tools.connectors.servicenow import ListServiceNowRecordsTool

    tool, context = ListServiceNowRecordsTool(), _context(_sn())
    first = await tool.execute({"table": "incident"}, context)
    assert first["count"] == 1 and world.idp.issued == 1
    await tool.execute({"table": "incident"}, context)
    assert world.idp.issued == 1, "cached"
    world.refuse_all = True
    refused = await tool.execute({"table": "incident"}, context)
    assert "error" in refused and world.idp.issued == 2 and SECRET not in str(refused)


def test_servicenow_explicit_modes_never_fall_back():
    token_and_basic = {"servicenow_token": "tok", "servicenow_username": "u", "servicenow_password": "p"}
    assert resolve_servicenow_auth({**token_and_basic, "servicenow_auth_mode": "basic"}).scheme == "basic"
    assert resolve_servicenow_auth({**token_and_basic, "servicenow_auth_mode": "oidc_client_credentials"}) is None
    no_token_url = {**_sn(), "servicenow_token_url": "", **token_and_basic}
    assert resolve_servicenow_auth(no_token_url) is None, "no oauth_token.do default"
    assert resolve_servicenow_auth({**_sn(), "servicenow_auth_mode": "bearer_token"}) is None
    assert resolve_servicenow_auth({"servicenow_auth_mode": "magic", "servicenow_token": "tok"}) is None


def test_without_a_mode_no_servicenow_credential_resolves():
    creds = {"servicenow_client_id": "octryx-client", "servicenow_client_secret": SECRET}
    basic = {"servicenow_username": "u", "servicenow_password": "p"}
    assert resolve_servicenow_auth({"servicenow_token": "tok", **creds, **basic}) is None
    assert resolve_servicenow_auth(basic) is None


def test_servicenow_save_validation():
    validate_servicenow_auth_config({"servicenow_url": SN_URL})  # nothing to sign in with yet
    with pytest.raises(AtlassianAuthConfigError):
        validate_servicenow_auth_config({"servicenow_token": "tok"})  # a credential needs its mode
    for config in ({"servicenow_auth_mode": "magic"}, {"servicenow_auth_mode": "basic", "servicenow_username": "u"},
                   {"servicenow_auth_mode": "oidc_client_credentials", "servicenow_client_id": "c"}):
        with pytest.raises(AtlassianAuthConfigError):
            validate_auth_config("servicenow", config)
    validate_auth_config("servicenow", _sn())


async def test_servicenow_knowledge_sync_uses_the_external_idp(world):
    connection = servicenow_connection(_sn())
    auth = await connection.request_auth(transport=world.transport())
    reader = SourceReader(auth, transport=world.transport())
    assert (await reader.get_json("/api/now/table/incident"))["result"]
    assert world.system_auth[-1] == "Bearer tok-1"
    without_mode = {key: value for key, value in _sn().items() if key != "servicenow_auth_mode"}
    with pytest.raises(ConnectorError) as refused:
        servicenow_connection(without_mode)
    assert refused.value.reason == REASON_CONNECTION_NOT_CONFIGURED
    world.idp.answer = (401, {"error": "invalid_client"})
    oidc_tokens.clear_token_cache()
    with pytest.raises(ConnectorError) as unauthorized:
        await servicenow_connection(_sn()).request_auth(transport=world.transport())
    assert unauthorized.value.reason == REASON_SOURCE_UNAUTHORIZED


@pytest.mark.parametrize(("error", "reason"), [
    (oidc.OidcTokenError(oidc.CODE_INVALID_CLIENT), REASON_SOURCE_UNAUTHORIZED),
    (oidc.OidcTokenError(oidc.CODE_UNAUTHORIZED_CLIENT), REASON_SOURCE_UNAUTHORIZED),
    (oidc.OidcTokenError(oidc.CODE_BAD_RESPONSE, http_status=400), REASON_SOURCE_UNAUTHORIZED),
    (oidc.OidcTokenError(oidc.CODE_BAD_RESPONSE), REASON_SOURCE_CONTRACT_VIOLATION),
    (oidc.OidcTokenError(oidc.CODE_TOKEN_ENDPOINT_REDIRECT, http_status=302), REASON_SOURCE_CONTRACT_VIOLATION),
    (oidc.OidcTokenError(oidc.CODE_TOKEN_ENDPOINT_UNREACHABLE), REASON_SOURCE_UNAVAILABLE),
    (oidc.OidcTokenError(oidc.CODE_TOKEN_ENDPOINT_UNREACHABLE, egress_refused=True), REASON_EGRESS_REFUSED),
    (oidc.OidcTokenError(oidc.CODE_TOKEN_URL_INVALID), REASON_CONNECTION_NOT_CONFIGURED),
])
def test_a_failed_grant_is_a_fixed_source_sync_reason(error, reason):
    from app.services.knowledge.sources.sync.token_errors import reason_for_token_error

    assert reason_for_token_error(error) == reason


# --- Knowledge sync (Atlassian) ----------------------------------------------------------------------------


async def test_knowledge_sync_reads_with_the_token_and_retries_once(world):
    from app.services.atlassian_auth import resolve_credential

    credential = resolve_credential(JIRA, _jira())
    connection = SourceConnection(kind="jira", base_url=JIRA_URL, principal=credential.principal,
                                  secret=credential.secret, scheme=credential.scheme, oidc=credential.oidc)
    assert "Authorization" not in connection.auth_headers() and SECRET not in repr(connection)
    reader = SourceReader(connection, transport=world.transport())
    assert (await reader.get_json("/rest/api/2/serverInfo"))["ok"]
    world.refuse_all = True
    with pytest.raises(ConnectorError) as refused:
        await reader.get_json("/rest/api/2/serverInfo")
    assert refused.value.reason == REASON_SOURCE_UNAUTHORIZED and world.idp.issued == 2
    world.idp.answer = (302, {})
    oidc_tokens.clear_token_cache()
    with pytest.raises(ConnectorError) as redirected:
        await reader.get_json("/rest/api/2/serverInfo")
    assert redirected.value.reason == REASON_SOURCE_CONTRACT_VIOLATION


# --- rebind, credential unit, presets, logs -----------------------------------------------------------------


@pytest.mark.parametrize(("tool", "field", "value"), [
    ("jira", "jira_oidc_token_url", "https://other-idp.test/token"),
    ("jira", "jira_oidc_client_id", "another-client"),
    ("jira", "jira_oidc_client_id", "OCTRYX-CLIENT"),  # client ids are case-sensitive
    ("servicenow", "servicenow_token_url", "https://other-idp.test/token"),
    ("servicenow", "servicenow_client_id", "another-client"),
])
def test_a_kept_secret_never_follows_a_new_token_url_or_client_id(tool, field, value):
    stored = (_jira() if tool == "jira" else _sn()) | {f"{tool}_{'oidc_' if tool == 'jira' else ''}client_secret": None}
    secret_field = "jira_oidc_client_secret" if tool == "jira" else "servicenow_client_secret"
    stored = {**stored, f"{secret_field}_secret_ref": "ref-1"}
    with pytest.raises(SecretRebindRequiredError) as refused:
        evaluate_secret_rebind(tool_name=tool, project_id=None, stored=stored, proposed={**stored, field: value},
                               submitted_secret_fields=set(), confirmed=False)
    assert field in refused.value.rebind.changed_target_fields
    assert evaluate_secret_rebind(tool_name=tool, project_id=None, stored=stored, proposed=dict(stored),
                                  submitted_secret_fields=set(), confirmed=False) is None
    assert evaluate_secret_rebind(tool_name=tool, project_id=None, stored=stored, proposed={**stored, field: value},
                                  submitted_secret_fields={secret_field}, confirmed=False) is None


def test_a_workspace_save_that_keeps_an_inherited_target_is_no_rebind():
    """A Workspace entry that never set the OIDC token URL already resolved to the global one;
    saving it again (deactivating, say) without that field moves no secret anywhere."""
    stored = {"jira_url": JIRA_URL, "jira_token_secret_ref": "ref-1"}
    inherited = {"jira_oidc_token_url": "https://idp.example.test/token"}
    assert evaluate_secret_rebind(tool_name="jira", project_id="ws-1", stored=stored, proposed=dict(stored),
                                  submitted_secret_fields=set(), confirmed=False, inherited=inherited) is None
    own_target = {**stored, "jira_oidc_token_url": "https://own-idp.example.test/token"}
    with pytest.raises(SecretRebindRequiredError) as refused:
        evaluate_secret_rebind(tool_name="jira", project_id="ws-1", stored=own_target, proposed=dict(stored),
                               submitted_secret_fields=set(), confirmed=False, inherited=inherited)
    assert refused.value.rebind.changed_target_fields == ("jira_oidc_token_url",)


def test_a_workspace_oidc_unit_never_mixes_with_global_credentials():
    global_config = {"jira_url": JIRA_URL, "jira_username": "svc", "jira_password": "pw", "jira_oidc_scope": "all",
                     "jira_oidc_audience": "global-aud", "jira_allowed_projects": ["OPS"]}
    inherited = global_config_for_scope("jira", global_config, _jira())
    assert inherited == {"jira_allowed_projects": ["OPS"]}


def test_the_presets_carry_no_example_host_principal_or_secret():
    for name in ("jira", "confluence", "servicenow"):
        example = TOOL_CONFIG_PRESETS[name]["example"]
        text = str(example)
        assert "service-now.com" not in text and "@" not in text
        assert not [key for key in example if key.endswith(("_client_id", "_secret", "_token", "_password",
                                                              "_token_url", "_username", "_email"))]
        assert all(str(example.get(key, "")).endswith(".example") for key in example if key.endswith("_url"))


async def test_no_secret_or_token_reaches_a_log_line_or_a_result(world, caplog):
    from app.services.connector_test.collab import test_jira_connection

    caplog.set_level(logging.DEBUG)
    results = [await _priorities(_jira()), await test_jira_connection(_jira(), httpx_module=httpx)]
    for answer in ((401, {"error": "invalid_client", "error_description": SECRET}), (302, {}), (200, {})):
        oidc_tokens.clear_token_cache()
        world.idp.answer = answer
        results.append(await test_jira_connection(_jira(), httpx_module=httpx))
        with pytest.raises(oidc.OidcTokenError) as failed:
            await oidc_tokens.access_token(request_auth(JIRA, _jira())._credentials)
        results.append(str(failed.value))
    text = caplog.text + repr(results) + repr(request_auth(JIRA, _jira())) + repr(resolve_servicenow_auth(_sn()))
    for value in (SECRET, "tok-1", "tok-2", base64.b64encode(f"octryx-client:{SECRET}".encode()).decode()):
        assert value not in text
