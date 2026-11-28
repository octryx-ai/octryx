"""Git authentication per mode, the connection test, named connection validation, the runtime guard and repository bootstrap."""

from __future__ import annotations

import httpx
import pytest
from fastapi import HTTPException

import app.services.connector_auth.oidc_client_credentials as oidc
import app.services.connector_auth.oidc_token_cache as oidc_tokens
from app.services.connector_auth.atlassian_modes import BITBUCKET_AUTH_MODES
from app.services.git_http_auth import bearer_header_env
from app.tools.bitbucket_impl import _bitbucket_internal_core as core
from app.tools.context import ToolContext
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

# --- Git ------------------------------------------------------------------------------------------------------


def test_the_git_header_is_scoped_to_the_remote_origin_and_comes_from_the_environment():
    env = bearer_header_env("https://bb.test:8443/bitbucket/scm/RIVER/ledger.git", PAT,
                            base={"GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": "core.x", "GIT_CONFIG_VALUE_0": "y",
                                  "GIT_ASKPASS": "/somewhere/askpass", "PATH": "/usr/bin"})
    assert env["GIT_CONFIG_COUNT"] == "3" and env["GIT_CONFIG_KEY_0"] == "core.x", "inherited config is kept"
    assert (env["GIT_CONFIG_KEY_1"], env["GIT_CONFIG_VALUE_1"]) == ("credential.helper", "")
    assert env["GIT_CONFIG_KEY_2"] == "http.https://bb.test:8443/.extraHeader"
    assert env["GIT_CONFIG_VALUE_2"] == f"Authorization: Bearer {PAT}"
    assert env["GIT_TERMINAL_PROMPT"] == "0" and "GIT_ASKPASS" not in env
    with pytest.raises(ValueError):
        bearer_header_env("https://bb.test/x.git", "bad\ntoken")
    with pytest.raises(ValueError):
        bearer_header_env("ssh://git@bb.test/x.git", PAT)


async def test_git_auth_env_per_mode():
    url = f"{BB_URL}/scm/RIVER/ledger.git"
    pat_env = await core._bitbucket_git_auth_env_async(_context(_pat()), url)
    assert pat_env["GIT_CONFIG_VALUE_" + str(int(pat_env["GIT_CONFIG_COUNT"]) - 1)] == f"Authorization: Bearer {PAT}"
    assert "OCTRYX_BITBUCKET_SECRET" not in pat_env and "GIT_ASKPASS" not in pat_env
    basic = {"bitbucket_url": BB_URL, "bitbucket_auth_mode": "basic", "bitbucket_username": "svc",
             "bitbucket_password": "pw"}
    basic_env = await core._bitbucket_git_auth_env_async(_context(basic), url)
    assert (basic_env["OCTRYX_BITBUCKET_USERNAME"], basic_env["OCTRYX_BITBUCKET_SECRET"]) == (
        "svc", "pw"), "a Basic sign-in answers through the askpass pair"
    with pytest.raises(ValueError, match="not this Bitbucket connection's host"):
        await core._bitbucket_git_auth_env_async(_context(_pat()), "https://evil.test/scm/RIVER/ledger.git")
    with pytest.raises(ValueError, match="credentials are required"):
        await core._bitbucket_git_auth_env_async(_context(_pat(bitbucket_token="")), url)


async def test_git_clone_sends_the_client_credentials_token_only_as_a_header(world, tmp_path, monkeypatch, db):  # noqa: F811
    from app.tools.registry import execute_tool
    from tests.support.tools_bitbucket_support import _create_bitbucket_policy_project

    repo_root = tmp_path / "var" / "repos" / "bitbucket" / "RIVER" / "ledger"
    project_id = await _create_bitbucket_policy_project(db, repo_root=str(repo_root))
    commands: list[list[str]] = []
    envs: list[dict[str, str] | None] = []

    async def fake_json_get(context, path, params=None):
        return {"displayId": "main"}

    async def fake_exec(*args, **kwargs):
        commands.append(list(args))
        envs.append(kwargs.get("env"))

        class FakeProcess:
            returncode = 0

            async def communicate(self):
                if list(args[:3]) == ["git", "rev-parse", "HEAD"]:
                    return (b"abc123\n", b"")
                if list(args[:2]) == ["git", "clone"]:
                    (repo_root / ".git").mkdir(parents=True, exist_ok=True)
                return (b"", b"")

        return FakeProcess()

    monkeypatch.setattr("app.tools.bitbucket_impl._bitbucket_internal_network._bitbucket_json_get", fake_json_get)
    monkeypatch.setattr("asyncio.create_subprocess_exec", fake_exec)
    config = {**_oidc(), "managed_repo_root": "var/repos/bitbucket",
              "tool_policy": {"allowlist": ["prepare_bitbucket_repository"]}}
    context = ToolContext(user_id="test", project_ids=[project_id], roles=["operator"], session_id="test", db=db,
                          project_config=config, workspace_root=str(tmp_path))
    result = await execute_tool("prepare_bitbucket_repository",
                                {"project_key": "RIVER", "repo_slug": "ledger", "branch_name": "codex/x"}, context)
    assert result.get("cloned") is True, result
    clone = next(command for command in commands if command[:2] == ["git", "clone"])
    assert clone[-2] == f"{BB_URL}/scm/RIVER/ledger.git", "no userinfo in the clone URL"
    argv = " ".join(" ".join(command) for command in commands)
    assert "tok-1" not in argv and SECRET not in argv and "Bearer" not in argv
    clone_env = envs[commands.index(clone)]
    headers = [value for key, value in clone_env.items() if key.startswith("GIT_CONFIG_VALUE_")]
    assert "Authorization: Bearer tok-1" in headers
    assert "http.https://bb.test/.extraHeader" in clone_env.values()
    assert not any(SECRET in value for value in clone_env.values()), "the client secret never reaches Git"
    assert "OCTRYX_BITBUCKET_SECRET" not in clone_env
    assert world.idp.issued == 1


# --- the connection test --------------------------------------------------------------------------------------


async def test_the_connection_test_with_client_credentials(world):  # noqa: F811
    from app.services.connector_test.collab import test_bitbucket_connection

    ok = await test_bitbucket_connection(_oidc(), httpx_module=httpx)
    assert ok["ok"] is True and world.system_auth == ["Bearer tok-1"]
    assert world.system_requests[0].url.path == "/bitbucket/rest/api/1.0/application-properties"

    world.refuse_all = True
    refused = await test_bitbucket_connection(_oidc(), httpx_module=httpx)
    assert refused["ok"] is False and refused["auth_code"] == oidc.CODE_CONNECTOR_UNAUTHORIZED

    world.refuse_all = False
    oidc_tokens.clear_token_cache()
    wrong = await test_bitbucket_connection(_oidc(bitbucket_oidc_client_secret="wrong"), httpx_module=httpx)
    assert wrong["auth_code"] == oidc.CODE_INVALID_CLIENT and "wrong" not in str(wrong)


async def test_the_connection_test_refuses_incomplete_or_cloud_server_modes():
    from app.services.connector_test.collab import test_bitbucket_connection

    incomplete = await test_bitbucket_connection(_pat(bitbucket_token=""), httpx_module=httpx)
    assert incomplete["ok"] is False and "Bitbucket HTTP access token" in incomplete["summary"]
    cloud = await test_bitbucket_connection(
        {**_pat(), "bitbucket_deployment": "cloud", "bitbucket_url": "https://bitbucket.org"}, httpx_module=httpx)
    assert cloud["ok"] is False and "Bitbucket Cloud" in cloud["summary"]
    without_mode = await test_bitbucket_connection({"bitbucket_url": BB_URL, "bitbucket_username": "svc"},
                                                   httpx_module=httpx)
    assert without_mode["ok"] is False and "bitbucket_auth_mode" in without_mode["summary"]


async def test_the_connection_test_sends_the_http_access_token(monkeypatch):
    import app.services.connector_test.collab as collab

    seen: list[httpx.Request] = []

    async def bitbucket(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"version": "9.4.0"})

    monkeypatch.setattr(collab, "egress_transport", lambda *_a, **_k: httpx.MockTransport(bitbucket))
    result = await collab.test_bitbucket_connection(_pat(), httpx_module=httpx)
    assert result["ok"] is True and seen[0].headers["Authorization"] == f"Bearer {PAT}"


# --- named connections and the connection types -----------------------------------------------------------------


async def test_named_connection_saves_validate_the_mode(db):
    from app.services.admin.project.named_connection_service import save_named
    from app.services.tool_config import upsert_tool_config
    from tests.knowledge_evidence_seed_support import seed_workspace

    workspace_id = await seed_workspace(db)
    await upsert_tool_config(db, tool_name="bitbucket", project_id=workspace_id,
                             config={"bitbucket_url": "https://bitbucket.example.test"}, is_active=True)

    async def save(body):
        return await save_named(db, connector="bitbucket", project_id=workspace_id, payload=body, actor_id=None)

    base = {"bound_scopes": ["RIVER/ledger"], "bitbucket_url": BB_URL}
    for body, text in (
        ({"bitbucket_auth_mode": "oidc_client_credentials", "bitbucket_oidc_token_url": IDP,
          "bitbucket_oidc_client_id": "octryx-client"}, "bitbucket_oidc_client_secret"),
        ({"bitbucket_auth_mode": "bearer_pat"}, "Bitbucket HTTP access token"),
        ({"bitbucket_auth_mode": "bearer_pat", "bitbucket_token": PAT, "bitbucket_deployment": "cloud",
          "bitbucket_url": "https://bitbucket.org"}, "Bitbucket Cloud"),
    ):
        with pytest.raises(HTTPException) as refused:
            await save({"name": "x", **base, **body})
        assert refused.value.status_code == 422 and text in str(refused.value.detail), body
    saved = await save({"name": "ledger", **base, "bitbucket_auth_mode": "oidc_client_credentials",
                        "bitbucket_oidc_token_url": IDP, "bitbucket_oidc_client_id": "octryx-client",
                        "bitbucket_oidc_client_secret": SECRET, "bitbucket_oidc_scope": "repo"})
    assert saved["secret_status"]["bitbucket_oidc_client_secret"] is True
    assert SECRET not in str(saved)


def test_the_runtime_guard_of_an_explicit_mode_needs_its_credential():
    from app.services.named_connections.descriptor import UnitIncompleteError
    from app.services.named_connections.descriptors.scm import BITBUCKET as DESCRIPTOR

    DESCRIPTOR.runtime_guard(_oidc())
    DESCRIPTOR.runtime_guard(_pat())
    with pytest.raises(UnitIncompleteError):
        DESCRIPTOR.runtime_guard(_oidc(bitbucket_oidc_client_secret=""))
    with pytest.raises(UnitIncompleteError):
        DESCRIPTOR.runtime_guard(_pat(bitbucket_token=""))


def test_the_connection_type_lists_the_modes_and_each_fields_kinds():
    from app.services.connections.catalog import list_connection_types

    entry = next(item for item in list_connection_types() if item["type"] == "bitbucket")
    assert entry["auth_kinds"] == list(BITBUCKET_AUTH_MODES) and entry["auth_kinds"][0] == "basic"
    fields = {item["key"]: item for item in entry["access_fields"]}
    assert fields["bitbucket_auth_mode"]["kind"] == "select"
    assert fields["bitbucket_oidc_client_secret"]["auth_kinds"] == ["oidc_client_credentials"]
    assert fields["bitbucket_oidc_scope"]["required"] is False
    assert set(fields["bitbucket_token"]["auth_kinds"]) == {"bearer_pat", "cloud_api_token"}
    assert fields["bitbucket_password"]["auth_kinds"] == ["basic"]
    assert "Cloud" not in fields["bitbucket_username"]["label"], "Data Center labels; the UI adds Cloud's"


# --- repository bootstrap --------------------------------------------------------------------------------------


async def test_repository_bootstrap_creates_with_the_token_and_never_puts_it_in_the_remote(world):  # noqa: F811
    from app.services.repository_bootstrap.providers import create_bitbucket_repository

    idp = world.handle

    async def bitbucket(request):
        if request.url.host == "idp.test":
            return await idp(request)
        world.system_auth.append(request.headers.get("Authorization"))
        return httpx.Response(201, json={"slug": "ledger"})

    world.handle = bitbucket
    created = await create_bitbucket_repository(project_config=_oidc(), config={"bitbucket_project_key": "RIVER"},
                                                repo_name="ledger")
    assert world.system_auth == ["Bearer tok-1"]
    assert created["clone_url"] == f"{BB_URL}/scm/RIVER/ledger.git" and "authenticated_clone_url" not in created
    assert "Authorization: Bearer tok-1" in created["git_env"].values()
    assert "http.https://bb.test/.extraHeader" in created["git_env"].values()

    basic = {"bitbucket_url": BB_URL, "bitbucket_auth_mode": "basic", "bitbucket_username": "svc",
             "bitbucket_password": "pw"}
    created = await create_bitbucket_repository(project_config=basic, config={"bitbucket_project_key": "RIVER"},
                                                repo_name="ledger")
    assert world.system_auth[-1] == _basic("svc", "pw")
    # A Basic sign-in never goes into the remote URL either: a header from the environment.
    assert created["clone_url"] == f"{BB_URL}/scm/RIVER/ledger.git" and "authenticated_clone_url" not in created
    assert f"Authorization: {_basic('svc', 'pw')}" in created["git_env"].values()
