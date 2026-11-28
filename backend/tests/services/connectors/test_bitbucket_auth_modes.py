"""Bitbucket Server/Data Center signs in like Jira (``bitbucket_auth_mode``): each mode's credential, validation,
REST and Git use, against local identity provider and Bitbucket stubs."""

from __future__ import annotations

import httpx
import pytest

import app.services.connector_auth.oidc_client_credentials as oidc
from app.services.connector_auth.atlassian import auth_headers, resolve_credential
from app.services.connector_auth.atlassian_modes import BITBUCKET, SCHEME_BEARER, SCHEME_OIDC, AtlassianAuthConfigError
from app.services.connector_auth.atlassian_validation import validate_auth_config
from app.services.tool_config.validation import validate_tool_config
from app.tools.bitbucket_impl import _bitbucket_internal_core as core
from app.tools.bitbucket_impl import _bitbucket_internal_network as network
from tests.services.connectors.bitbucket_auth_modes_support import (  # noqa: F401
    BB_URL,
    PAT,
    _basic,
    _context,
    _oidc,
    _pat,
    world,
)
from tests.support.oidc_stub_support import IDP, SECRET


def test_each_mode_builds_its_own_header_and_never_falls_back():
    base = {"bitbucket_url": BB_URL, "bitbucket_username": "svc", "bitbucket_password": "pw", "bitbucket_token": PAT}
    assert auth_headers(BITBUCKET, {**base, "bitbucket_auth_mode": "basic"}) == {"Authorization": _basic("svc", "pw")}
    assert auth_headers(BITBUCKET, {**base, "bitbucket_auth_mode": "bearer_pat"}) == {"Authorization": f"Bearer {PAT}"}
    assert auth_headers(BITBUCKET, {**base, "bitbucket_auth_mode": "cloud_api_token"}) == {
        "Authorization": _basic("svc", PAT)}
    assert resolve_credential(BITBUCKET, {**base, "bitbucket_auth_mode": "basic", "bitbucket_password": ""}) is None
    assert resolve_credential(BITBUCKET, {**base, "bitbucket_auth_mode": "bearer_pat", "bitbucket_token": ""}) is None
    assert resolve_credential(BITBUCKET, {**base, "bitbucket_auth_mode": "kerberos"}) is None, "unknown: fail closed"
    pat = resolve_credential(BITBUCKET, {"bitbucket_auth_mode": "bearer_pat", "bitbucket_token": PAT})
    assert pat.scheme == SCHEME_BEARER and pat.principal == "", "a Bearer token needs no username"
    assert PAT not in repr(pat)


def test_client_credentials_have_no_static_header():
    credential = resolve_credential(BITBUCKET, _oidc())
    assert credential.scheme == SCHEME_OIDC and credential.oidc.token_url == IDP
    assert credential.oidc.connection == "bitbucket", "the token request goes through Bitbucket's egress rule"
    assert credential.headers() == {}
    assert SECRET not in repr(credential)
    assert resolve_credential(BITBUCKET, _oidc(bitbucket_oidc_client_secret="")) is None


def test_without_a_mode_no_credential_resolves_and_a_server_save_is_refused():
    both = {"bitbucket_username": "svc", "bitbucket_password": "pw", "bitbucket_token": PAT}
    assert resolve_credential(BITBUCKET, both) is None and auth_headers(BITBUCKET, both) == {}
    assert resolve_credential(BITBUCKET, {"bitbucket_token": PAT}) is None
    with pytest.raises(AtlassianAuthConfigError, match="Bitbucket credentials need bitbucket_auth_mode"):
        validate_auth_config(BITBUCKET, {"bitbucket_url": BB_URL, **both})
    validate_auth_config(BITBUCKET, {"bitbucket_deployment": "cloud", "bitbucket_url": "https://bitbucket.org",
                                     "bitbucket_username": "me@example.com", "bitbucket_token": "t"})


def test_save_validation_names_fields_and_refuses_cloud_with_a_server_mode():
    with pytest.raises(AtlassianAuthConfigError, match="bitbucket_auth_mode must be one of"):
        validate_auth_config(BITBUCKET, {"bitbucket_auth_mode": "kerberos"})
    with pytest.raises(AtlassianAuthConfigError, match="Bitbucket HTTP access token"):
        validate_auth_config(BITBUCKET, {"bitbucket_url": BB_URL, "bitbucket_auth_mode": "bearer_pat"})
    with pytest.raises(AtlassianAuthConfigError, match="Bitbucket username"):
        validate_auth_config(BITBUCKET, {"bitbucket_auth_mode": "basic", "bitbucket_password": "pw"})
    with pytest.raises(AtlassianAuthConfigError) as missing:
        validate_auth_config(BITBUCKET, _oidc(bitbucket_oidc_token_url="", bitbucket_oidc_client_secret=""))
    assert "bitbucket_oidc_token_url" in str(missing.value) and "bitbucket_oidc_client_secret" in str(missing.value)
    assert SECRET not in str(missing.value)
    with pytest.raises(AtlassianAuthConfigError) as bad_url:
        validate_auth_config(BITBUCKET, _oidc(bitbucket_oidc_token_url="http://idp.test/token"))
    assert bad_url.value.code == oidc.CODE_TOKEN_URL_INVALID
    validate_auth_config(BITBUCKET, _oidc(bitbucket_oidc_client_secret=None,
                                          bitbucket_oidc_client_secret_secret_ref="sec-1"))
    cloud = {"bitbucket_deployment": "cloud", "bitbucket_url": "https://bitbucket.org",
             "bitbucket_username": "me@example.com", "bitbucket_token": "t"}
    validate_auth_config(BITBUCKET, {**cloud, "bitbucket_auth_mode": "cloud_api_token"})
    for mode in ("basic", "bearer_pat", "oidc_client_credentials"):
        with pytest.raises(AtlassianAuthConfigError, match="Bitbucket Cloud"):
            validate_auth_config(BITBUCKET, {**_oidc(), **cloud, "bitbucket_password": "pw", "bitbucket_auth_mode": mode})


def test_the_preset_accepts_the_new_fields():
    config = _oidc(bitbucket_oidc_scope="repo", bitbucket_oidc_audience="bb", bitbucket_oidc_client_auth="client_secret_basic")
    assert validate_tool_config("bitbucket", config) == config
    with pytest.raises(ValueError, match="bitbucket_oidc_client_auth"):
        validate_tool_config("bitbucket", _oidc(bitbucket_oidc_client_auth="private_key_jwt"))


async def test_a_tool_call_sends_the_http_access_token_as_bearer(monkeypatch):
    seen: list[httpx.Request] = []

    async def bitbucket(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"displayId": "main"})

    monkeypatch.setattr(network, "egress_transport", lambda *_a, **_k: httpx.MockTransport(bitbucket))
    payload = await network._bitbucket_json_get(
        _context(_pat()), "/rest/api/1.0/projects/RIVER/repos/ledger/branches/default")
    assert payload == {"displayId": "main"}
    assert seen[0].headers["Authorization"] == f"Bearer {PAT}"
    assert str(seen[0].url).startswith(BB_URL)


async def test_a_tool_call_uses_the_client_credentials_token_and_retries_once_on_401(world):  # noqa: F811
    context = _context(_oidc())
    await network._bitbucket_json_get(context, "/rest/api/1.0/projects/RIVER/repos/ledger/branches")
    await network._bitbucket_json_get(context, "/rest/api/1.0/projects/RIVER/repos/ledger/branches")
    assert world.idp.issued == 1, "the token is cached across calls"
    assert world.system_auth == ["Bearer tok-1", "Bearer tok-1"]

    world.system_auth.clear()
    original = world.handle

    async def revoke_once(request):
        if request.url.host != "idp.test" and request.headers.get("Authorization") == "Bearer tok-1":
            world.system_auth.append("Bearer tok-1")
            return httpx.Response(401)
        return await original(request)

    world.handle = revoke_once
    await network._bitbucket_json_get(context, "/rest/api/1.0/projects/RIVER/repos/ledger/branches")
    assert world.system_auth == ["Bearer tok-1", "Bearer tok-2"] and world.idp.issued == 2

    world.refuse_all, world.handle = True, original
    world.system_auth.clear()
    with pytest.raises(httpx.HTTPStatusError):
        await network._bitbucket_json_get(context, "/rest/api/1.0/projects/RIVER/repos/ledger/branches")
    assert len(world.system_auth) == 2, "one retry with a fresh token, no more"


async def test_a_reading_tool_sends_the_token_to_the_raw_file_endpoint(world):  # noqa: F811
    from app.tools.bitbucket_impl._bitbucket_repository_base import ReadBitbucketFile

    result = await ReadBitbucketFile().execute({"project_key": "RIVER", "repo_slug": "ledger", "path": "a.py"},
                                               _context(_oidc()))
    assert "error" not in result
    assert world.system_auth == ["Bearer tok-1"]


async def test_a_basic_tool_call_uses_its_pair():
    basic = {"bitbucket_url": BB_URL, "bitbucket_auth_mode": "basic", "bitbucket_username": "svc",
             "bitbucket_password": "pw", "bitbucket_token": PAT}
    assert await core._bitbucket_http_auth(_context(basic)) == ("svc", "pw")
    assert await core._bitbucket_credentials_async(_context(basic)) == ("svc", "pw")
    assert await core._bitbucket_credentials_async(_context(_pat())) is None, "a Bearer token has no Basic pair"


async def test_the_client_secret_resolves_from_its_secret_ref_inside_the_connector(db):
    from app.services.secret import set_secret_value

    secret = await set_secret_value(db, tool_name="bitbucket", field_name="bitbucket_oidc_client_secret",
                                    project_id=None, value=SECRET)
    await db.commit()
    config = {**_oidc(), "bitbucket_oidc_client_secret": None, "bitbucket_oidc_client_secret_secret_ref": secret.id}
    credential = await core._bitbucket_credential(_context(config, db=db))
    assert credential is not None and credential.oidc.client_secret == SECRET
