"""Contract: ServiceNow OAuth with the password grant and its refresh token (mode ``oauth_password``)."""

from __future__ import annotations

import logging

import httpx
import pytest

import app.services.connector_auth.servicenow_password_grant as grant_module
from app.services.connector_auth.atlassian_modes import AtlassianAuthConfigError
from app.services.connector_auth.atlassian_validation import validate_auth_config
from app.services.connector_auth.servicenow import resolve_servicenow_auth
from app.services.connector_test.servicenow import test_servicenow_connection as connection_test
from app.services.tool_config.secret_rebind import SecretRebindRequiredError, evaluate_secret_rebind
from app.tools.context import ToolContext
from tests.servicenow_stub_support import CLIENT_SECRET, PASSWORD, StubInstance, config, stub_instance


@pytest.fixture
def sn(monkeypatch):
    yield from stub_instance(monkeypatch, StubInstance())


def _context(cfg: dict) -> ToolContext:
    return ToolContext(user_id="u1", project_ids=[], roles=["admin"], session_id="s1", project_config=cfg,
                       workspace_root="/tmp")


async def _incidents(cfg: dict | None = None) -> dict:
    from app.tools.connectors.servicenow import ListServiceNowIncidentsTool

    return await ListServiceNowIncidentsTool().execute({}, _context(cfg or config()))


async def test_the_password_grant_sends_its_form_and_the_token_is_reused(sn):
    first, second = await _incidents(), await _incidents()
    assert first["count"] == second["count"] == 3 and len(sn.token_forms) == 1
    assert sn.token_forms[0] == {"grant_type": "password", "username": "integration.user", "password": PASSWORD,
                                 "client_id": "octryx-client", "client_secret": CLIENT_SECRET}
    assert {auth for _path, _params, auth in sn.api_requests} == {"Bearer tok-1"}


async def test_the_scope_is_sent_only_when_set(sn):
    await _incidents(config(servicenow_oauth_scope="useraccount"))
    assert sn.token_forms[0]["scope"] == "useraccount"


async def test_an_expiring_token_is_renewed_with_the_refresh_token(sn, monkeypatch):
    clock = [1000.0]
    monkeypatch.setattr(grant_module, "_now", lambda: clock[0])
    await _incidents()
    clock[0] += 1800 - 59
    await _incidents()
    assert [form["grant_type"] for form in sn.token_forms] == ["password", "refresh_token"]
    assert sn.token_forms[1]["refresh_token"] == "ref-1" and "password" not in sn.token_forms[1]
    assert sn.api_requests[-1][2] == "Bearer tok-2"


async def test_a_refused_refresh_token_falls_back_to_the_password_grant(sn, monkeypatch):
    clock = [1000.0]
    monkeypatch.setattr(grant_module, "_now", lambda: clock[0])
    await _incidents()
    sn.refresh_refused = True
    clock[0] += 1800
    result = await _incidents()
    assert result["count"] == 3
    assert [form["grant_type"] for form in sn.token_forms] == ["password", "refresh_token", "password"]


async def test_a_401_renews_the_token_and_retries_exactly_once(sn):
    await _incidents()
    original = sn._api

    def revoke_first(request):
        if request.headers.get("Authorization") == "Bearer tok-1":
            sn.api_requests.append((request.url.path, {}, "Bearer tok-1"))
            return httpx.Response(401)
        return original(request)

    sn._api = revoke_first
    assert (await _incidents())["count"] == 3
    assert [auth for _path, _params, auth in sn.api_requests[-2:]] == ["Bearer tok-1", "Bearer tok-2"]


@pytest.mark.parametrize(("answer", "code"), [
    ((400, {"error": "invalid_grant"}), "oauth_invalid_grant"),
    ((401, {"error": "invalid_client"}), "oauth_invalid_client"),
    ((401, {}), "oauth_invalid_client"),
    ((400, {"error": "unauthorized_client"}), "oauth_unauthorized_client"),
    ((302, {}), "oauth_token_endpoint_redirect"),
    ((200, {"token_type": "Bearer"}), "oauth_bad_response"),
    ((200, {"access_token": "t", "token_type": "mac"}), "oauth_bad_response"),
    ((503, {}), "oidc_token_endpoint_unreachable"),
])
async def test_every_token_failure_is_coded_in_the_connection_test(sn, answer, code):
    sn.token_answer = answer
    result = await connection_test(config(), httpx_module=httpx)
    assert result["ok"] is False and result["auth_code"] == code
    assert sn.api_requests == [] and len(sn.token_forms) == 1, "no redirect followed, no endpoint reached"


async def test_a_wrong_password_is_invalid_grant(sn):
    result = await connection_test(config(servicenow_password="wrong"), httpx_module=httpx)
    assert result["auth_code"] == "oauth_invalid_grant"


def test_the_mode_needs_all_its_fields_and_never_falls_back():
    for missing in ("servicenow_token_url", "servicenow_client_id", "servicenow_client_secret",
                    "servicenow_username", "servicenow_password"):
        incomplete = {**config(), missing: "", "servicenow_token": "static-token"}
        assert resolve_servicenow_auth(incomplete) is None, missing
        with pytest.raises(AtlassianAuthConfigError) as refused:
            validate_auth_config("servicenow", incomplete)
        assert missing in str(refused.value)
    with pytest.raises(AtlassianAuthConfigError) as plain_http:
        validate_auth_config("servicenow", config(servicenow_token_url="http://servicenow.test/oauth_token.do"))
    assert plain_http.value.code == "oidc_token_url_invalid"
    assert resolve_servicenow_auth(config(servicenow_token_url="http://servicenow.test/t")) is None
    loopback = resolve_servicenow_auth(config(servicenow_token_url="http://127.0.0.1:9/oauth_token.do"))
    assert loopback is not None and loopback.headers() == {} and loopback.http_auth() is not None
    validate_auth_config("servicenow", config())


@pytest.mark.parametrize(("field", "value"), [
    ("servicenow_token_url", "https://other.servicenow.test/oauth_token.do"),
    ("servicenow_client_id", "another-client"),
    ("servicenow_username", "another.user"),
])
def test_a_kept_secret_never_follows_a_new_token_url_client_or_user(field, value):
    stored = {**config(), "servicenow_client_secret": None, "servicenow_password": None,
              "servicenow_client_secret_secret_ref": "ref-1", "servicenow_password_secret_ref": "ref-2"}
    with pytest.raises(SecretRebindRequiredError) as refused:
        evaluate_secret_rebind(tool_name="servicenow", project_id=None, stored=stored,
                               proposed={**stored, field: value}, submitted_secret_fields=set(), confirmed=False)
    assert field in refused.value.rebind.changed_target_fields
    assert evaluate_secret_rebind(tool_name="servicenow", project_id=None, stored=stored, proposed=dict(stored),
                                  submitted_secret_fields=set(), confirmed=False) is None


async def test_no_secret_password_or_token_reaches_a_log_or_a_result(sn, caplog):
    caplog.set_level(logging.DEBUG)
    results: list[object] = [await _incidents(), await connection_test(config(), httpx_module=httpx)]
    for answer in ((400, {"error": "invalid_grant", "error_description": PASSWORD}), (302, {}), (200, {})):
        grant_module.clear_password_token_cache()
        sn.token_answer = answer
        results.append(await connection_test(config(), httpx_module=httpx))
        results.append(await _incidents())
    credential = resolve_servicenow_auth(config())
    text = caplog.text + repr(results) + repr(credential) + repr(credential.http_auth())
    for value in (CLIENT_SECRET, PASSWORD, "tok-1", "ref-1"):
        assert value not in text


async def test_the_grant_itself_refuses_a_plain_http_token_url(sn):
    credentials = grant_module.PasswordGrantCredentials(
        token_url="http://servicenow.test/oauth_token.do", client_id="octryx-client", client_secret=CLIENT_SECRET,
        username="integration.user", password=PASSWORD,
    )
    with pytest.raises(grant_module.OAuthPasswordError) as refused:
        await grant_module.access_token(credentials)
    assert refused.value.code == "oidc_token_url_invalid" and sn.token_forms == []
