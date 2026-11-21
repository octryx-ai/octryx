"""Contract: OpenID Connect client credentials for Confluence and Jira (tools, connection test, intake).

A local stub identity provider issues short-lived tokens; the stub systems accept only ``Bearer <current
token>`` (``oidc_stub_support.py``). Covered: token fetch and client authentication, the cache, refresh
before expiry, one fetch in flight, the single retry on a 401, every error code, the token URL rules, no
redirect, and save validation. ServiceNow, Source Sync, rebind and logs: ``test_oidc_servicenow_and_sync.py``.
"""

from __future__ import annotations

import asyncio
import base64

import httpx
import pytest

import app.services.oidc_client_credentials as oidc
import app.services.oidc_token_cache as oidc_tokens
from app.services.atlassian_auth import auth_headers, request_auth
from app.services.atlassian_auth_modes import CONFLUENCE, JIRA, AtlassianAuthConfigError
from app.services.atlassian_auth_validation import validate_auth_config
from tests.oidc_stub_support import (
    IDP,
    SECRET,
    _context,
    _form,
    _jira,
    _priorities,
    _wiki,
    stub_world,
)

# --- token fetch, client authentication, cache -------------------------------------------------------


@pytest.fixture
def world(monkeypatch):
    yield from stub_world(monkeypatch)


async def test_a_jira_tool_fetches_one_token_and_reuses_it(world):
    first, second = await _priorities(_jira()), await _priorities(_jira())
    assert first["priorities"] == second["priorities"] == [{"id": "1", "name": "High", "description": None}]
    assert len(world.idp.requests) == 1, "the token is cached"
    form = _form(world.idp.requests[0])
    assert form == {"grant_type": "client_credentials", "client_id": "octryx-client", "client_secret": SECRET}
    assert "Authorization" not in world.idp.requests[0].headers
    assert auth_headers(JIRA, _jira()) == {}, "no static header in client credentials mode"


async def test_scope_audience_and_client_secret_basic_are_sent_only_when_set(world):
    config = _jira(jira_oidc_scope="read", jira_oidc_audience="jira-api", jira_oidc_client_auth="client_secret_basic")
    await _priorities(config)
    request = world.idp.requests[0]
    assert _form(request) == {"grant_type": "client_credentials", "scope": "read", "audience": "jira-api"}
    assert request.headers["Authorization"] == f"Basic {base64.b64encode(f'octryx-client:{SECRET}'.encode()).decode()}"


async def test_the_token_is_refreshed_when_less_than_a_minute_remains(world, monkeypatch):
    clock = [1000.0]
    monkeypatch.setattr(oidc_tokens, "_now", lambda: clock[0])
    world.idp.expires_in = 120
    await _priorities(_jira())
    clock[0] += 59  # 61 s remain: still used
    await _priorities(_jira())
    assert world.idp.issued == 1
    clock[0] += 2  # 59 s remain: refreshed before the call
    await _priorities(_jira())
    assert world.idp.issued == 2
    assert world.system_auth[-1] == "Bearer tok-2"


async def test_without_expires_in_a_token_is_not_reused(world):
    world.idp.expires_in = None
    await _priorities(_jira())
    await _priorities(_jira())
    assert world.idp.issued == 2


@pytest.mark.parametrize(("expires_in", "reused_until"), [
    (10**12, 3600),  # capped at one hour: never cached for a day, let alone forever
    ("1e300", 3600),
    ("inf", None),  # non-finite: the conservative default, not reused
    ("-inf", None),
    ("nan", None),
    (-5, None),
])
async def test_a_huge_or_non_finite_expires_in_never_caches_a_token_forever(world, monkeypatch, expires_in, reused_until):
    clock = [1000.0]
    monkeypatch.setattr(oidc_tokens, "_now", lambda: clock[0])
    world.idp.expires_in = expires_in
    await _priorities(_jira())
    if reused_until is None:
        await _priorities(_jira())
        assert world.idp.issued == 2
        return
    clock[0] += reused_until - oidc.REFRESH_MARGIN_SECONDS - 1
    await _priorities(_jira())
    assert world.idp.issued == 1
    clock[0] += 2
    await _priorities(_jira())
    assert world.idp.issued == 2


def test_a_json_infinity_is_the_default_lifetime():
    # ``json`` reads a literal ``Infinity`` or ``1e400`` as float infinity
    assert oidc_tokens._lifetime(float("inf")) == oidc_tokens._lifetime(float("nan")) == oidc.DEFAULT_LIFETIME_SECONDS
    assert oidc_tokens._lifetime(-5) == oidc_tokens._lifetime(0) == oidc.DEFAULT_LIFETIME_SECONDS
    assert oidc_tokens._lifetime(7200) == 3600 and oidc_tokens._lifetime("300") == 300


async def test_free_locks_are_dropped(world):
    first = request_auth(JIRA, _jira())._credentials
    await oidc_tokens.access_token(first)
    oidc_tokens.invalidate(first)
    await oidc_tokens.access_token(request_auth(JIRA, _jira(jira_oidc_scope="read"))._credentials)
    assert [key for _loop, key in oidc_tokens._locks] == [request_auth(JIRA, _jira(jira_oidc_scope="read"))._credentials.cache_key()]


async def test_one_fetch_is_in_flight_per_client(world):
    world.idp.delay = 0.05
    credentials = request_auth(JIRA, _jira())._credentials
    tokens = await asyncio.gather(*(oidc_tokens.access_token(credentials) for _ in range(5)))
    assert set(tokens) == {"tok-1"} and len(world.idp.requests) == 1


async def test_a_changed_secret_never_reuses_the_cached_token(world):
    await _priorities(_jira())
    with pytest.raises(oidc.OidcTokenError) as refused:
        await _priorities(_jira(jira_oidc_client_secret="other"))  # a new cache key: the IdP refuses it
    assert refused.value.code == oidc.CODE_INVALID_CLIENT
    assert len(world.idp.requests) == 2


async def test_a_confluence_tool_sends_the_token(world):
    from app.tools.confluence import SearchConfluence

    result = await SearchConfluence().execute({"query": "runbook"}, _context(_wiki()))
    assert "error" not in result and world.system_auth == ["Bearer tok-1"]


async def _workspace(db, config: dict) -> str:
    from app.models import BuiltInToolConfig, Project

    project = Project(name=f"oidc-{len(config)}-{id(config)}", config={})
    db.add(project)
    await db.flush()
    db.add(BuiltInToolConfig(tool_name="jira", project_id=project.id, config=config, is_active=True))
    await db.commit()
    return project.id


async def test_the_jira_intake_and_the_state_sync_send_the_token(world, db):
    from app.models import WorkItem, WorkItemSyncConfig
    from app.services.secure_work.jira.jira_connector import fetch_jira_issues_for_sync
    from app.services.secure_work.jira.jira_state_sync import check_offered_transition

    project_id = await _workspace(db, _jira())
    intake = WorkItemSyncConfig(project_id=project_id, name="oidc", filters_json={}, field_mapping_json={},
                                sync_options_json={})
    fetched = await fetch_jira_issues_for_sync(db, config=intake, jql="project = OPS", limit=5)
    assert fetched.get("configured") is not False and world.system_auth == ["Bearer tok-1"]
    item = WorkItem(project_id=project_id, source_type="jira", source_instance="oidc", source_key="OPS-1",
                    title="OPS-1", work_state="intake", sync_state="imported")
    preview = {"jira_sync_preview": {"will_mutate_jira": True, "transition": "Done", "target_status": "Done"}}
    await check_offered_transition(db, item=item, preview=preview)
    assert preview["jira_sync_preview"]["offered_transitions"] == [{"name": "Done", "to": "Done"}]
    assert world.system_auth[-1] == "Bearer tok-1"


# --- the 401 retry --------------------------------------------------------------------------------------


async def test_a_401_renews_the_token_and_retries_exactly_once(world):
    await _priorities(_jira())
    world.system_auth.clear()
    original = world.handle

    async def revoke_once(request):  # the system revoked tok-1 before it expired
        if request.url.host != "idp.test" and request.headers.get("Authorization") == "Bearer tok-1":
            world.system_auth.append("Bearer tok-1")
            return httpx.Response(401)
        return await original(request)

    world.handle = revoke_once
    result = await _priorities(_jira())
    assert result["priorities"] and world.idp.issued == 2
    assert world.system_auth == ["Bearer tok-1", "Bearer tok-2"]


async def test_a_second_401_is_the_systems_answer(world):
    from app.services.connector_test.collab import test_jira_connection

    world.refuse_all = True
    result = await test_jira_connection(_jira(), httpx_module=httpx)
    assert result["ok"] is False and result["auth_code"] == oidc.CODE_CONNECTOR_UNAUTHORIZED
    assert "technical user" in result["auth_hint"]
    assert len(world.system_requests) == 2 and world.idp.issued == 2, "one retry with a fresh token, no more"


# --- error codes and the token endpoint -------------------------------------------------------------------


@pytest.mark.parametrize(("answer", "code"), [
    ((401, {"error": "invalid_client"}), oidc.CODE_INVALID_CLIENT),
    ((400, {"error": "invalid_client"}), oidc.CODE_INVALID_CLIENT),
    ((400, {"error": "unauthorized_client"}), oidc.CODE_UNAUTHORIZED_CLIENT),
    ((200, {"token_type": "Bearer"}), oidc.CODE_BAD_RESPONSE),
    ((200, {"access_token": "t", "token_type": "mac"}), oidc.CODE_BAD_RESPONSE),
    ((400, {"error": "invalid_scope"}), oidc.CODE_BAD_RESPONSE),
    ((503, {}), oidc.CODE_TOKEN_ENDPOINT_UNREACHABLE),
    ((302, {}), oidc.CODE_TOKEN_ENDPOINT_REDIRECT),
])
async def test_every_idp_failure_has_its_code_in_the_connection_test(world, answer, code):
    from app.services.connector_test.collab import test_confluence_connection

    world.idp.answer = answer
    result = await test_confluence_connection(_wiki(), httpx_module=httpx)
    assert result["ok"] is False and result["auth_code"] == code
    assert world.system_requests == [], "nothing reaches the system without a token"
    assert len(world.idp.requests) == 1, "a redirect is never followed, so the secret is sent once"


async def test_an_unreachable_token_endpoint_is_coded(world):
    async def down(request):
        raise httpx.ConnectError("refused", request=request)

    world.idp.__call__ = down
    world.handle = lambda request: down(request)
    from app.services.connector_test.collab import test_jira_connection

    result = await test_jira_connection(_jira(), httpx_module=httpx)
    assert result["auth_code"] == oidc.CODE_TOKEN_ENDPOINT_UNREACHABLE


async def test_the_connection_test_succeeds_with_client_credentials(world):
    from app.services.connector_test.collab import test_confluence_connection, test_jira_connection

    assert (await test_jira_connection(_jira(), httpx_module=httpx))["ok"] is True
    assert (await test_confluence_connection(_wiki(), httpx_module=httpx))["ok"] is True
    assert world.idp.issued == 1, "Jira and Confluence of the same client share one token"


async def test_a_wrong_secret_is_oidc_invalid_client(world):
    from app.services.connector_test.collab import test_jira_connection

    result = await test_jira_connection(_jira(jira_oidc_client_secret="wrong"), httpx_module=httpx)
    assert result["auth_code"] == oidc.CODE_INVALID_CLIENT and result["ok"] is False


@pytest.mark.parametrize(("url", "ok"), [
    (IDP, True),
    ("http://127.0.0.1:8099/token", True),
    ("http://localhost:8099/token", True),
    ("http://idp.test/token", False),
    ("https://svc:pw@idp.test/token", False),
    ("ht\ttps://u:p@idp.test/token", False),
    ("https: //idp.test/token", False),
    ("https://idp .test/token", False),
    ("https://idp.test/to\tken", False),
    ("ftp://idp.test/token", False),
    ("https:///token", False),
    ("", False),
])
def test_the_token_url_rules(url, ok):
    assert (oidc.token_url_problem(url) is None) is ok


async def test_the_token_endpoint_passes_the_egress_rule(monkeypatch):
    """With the real pinned transport a metadata address is refused before anything is sent."""
    oidc_tokens.clear_token_cache()
    seen: list[httpx.Request] = []
    stub = httpx.MockTransport(lambda request: seen.append(request) or httpx.Response(200, json={}))
    credentials = oidc.OidcClientCredentials("jira", "https://169.254.169.254/token", "octryx-client", SECRET)
    with pytest.raises(oidc.OidcTokenError) as refused:
        await oidc_tokens.access_token(credentials, transport=stub)
    assert refused.value.code == oidc.CODE_TOKEN_ENDPOINT_UNREACHABLE and refused.value.egress_refused
    assert seen == []


def test_save_validation_names_fields_and_refuses_bad_values():
    with pytest.raises(AtlassianAuthConfigError) as missing:
        validate_auth_config(JIRA, {"jira_auth_mode": "oidc_client_credentials"})
    assert "jira_oidc_token_url" in str(missing.value) and "jira_oidc_client_secret" in str(missing.value)
    with pytest.raises(AtlassianAuthConfigError) as plain_http:
        validate_auth_config(CONFLUENCE, _wiki(confluence_oidc_token_url="http://idp.test/token"))
    assert plain_http.value.code == oidc.CODE_TOKEN_URL_INVALID
    with pytest.raises(AtlassianAuthConfigError):
        validate_auth_config(JIRA, _jira(jira_oidc_client_auth="private_key_jwt"))
    stored_secret = {**_jira(), "jira_oidc_client_secret": None, "jira_oidc_client_secret_secret_ref": "ref-1"}
    validate_auth_config(JIRA, stored_secret)  # a stored secret counts
    assert request_auth(JIRA, _jira(jira_oidc_token_url="http://idp.test/t")) is None, "fails closed at runtime"
