"""A Bitbucket Data Center repository source with its own Git token.

Data Center answers 500 on ``/scm/`` for the connection's OpenID Connect token, so a repository registered from the
connection may carry a Bitbucket HTTP access token for Git:

- registration checks it against exactly that repository (``GET /rest/api/1.0/projects/{KEY}/repos/{slug}`` with the
  token as Bearer, through the ``bitbucket`` egress rule) before anything is saved: 401 ``git_token_invalid``,
  403/404 or another repository ``git_token_wrong_repository``, a public source ``git_token_not_supported``;
- it is stored encrypted in ``stored_secrets`` (never the plaintext), never answered (only ``configured``,
  ``set_at``, ``set_by``), replaced and removed through ``/git-token`` (audited without the value), and removed with
  the last source of its repository;
- the sync's clone sends it as the Bearer header instead of the connection's token; without it the connection's
  OpenID Connect token is used; the Bitbucket tools' Git environment (workflow runs) uses it too.
"""

from __future__ import annotations

import ipaddress
import json
import uuid
from urllib.parse import parse_qs

import httpx
import pytest
from sqlalchemy import select

import app.services.knowledge.sources.connection_repositories as listing_module
import app.services.knowledge.sources.repository_git_token as token_module
import app.services.knowledge.sources.sync.git_clone as git_clone
import app.services.oidc_token_cache as oidc_tokens
from app.models import AuditLog, ConnectionWorkspace, ConnectorNamedConnection, RepositoryGitToken, StoredSecret
from app.models.project.knowledge_source_sync import KnowledgeSourceConnector
from app.services.atlassian_auth import resolve_credential
from app.services.atlassian_auth_modes import BITBUCKET
from app.services.knowledge.access.authorization import authorize_workspace
from app.services.knowledge.sources.repository_access import RepositoryIdentity
from app.services.knowledge.sources.repository_git_token import CheckedGitToken, check_git_token
from app.services.knowledge.sources.sync.contract import ConnectorError
from app.services.knowledge.sources.sync.git_clone import GitCloneReader
from app.services.knowledge.sources.sync.git_cloud import ConnectedGitConnection
from app.services.knowledge.sources.sync.service_run import run_connector
from app.services.named_connections.contract import named_secret_field
from app.services.outbound_egress import egress_transport as real_egress_transport
from app.services.secret import decrypt_secret, set_secret_value
from app.tools.bitbucket_impl import _bitbucket_internal_core as core
from app.tools.context import ToolContext
from tests.knowledge_evidence_runtime_support import build_runtime
from tests.knowledge_evidence_seed_support import fetch_user, seed_member, seed_workspace
from tests.policy_engine_support import bearer

BASE = "https://bitbucket.example.test/bitbucket"
IDP = "https://idp.example.test/realms/r/protocol/openid-connect/token"
SECRET = "s3cr3t-client-value"
REPO_URL = f"{BASE}/projects/SHOP/repos/aws-shop-deployment"
CLONE_URL = f"{BASE}/scm/shop/aws-shop-deployment.git"
REPO_API = "/bitbucket/scm/shop/aws-shop-deployment.git/info/refs"  # the push discovery
TOKEN = "BBDC-repo-token-0001"
NEW_TOKEN = "BBDC-repo-token-0002"
RECEIVE_PACK = "application/x-git-receive-pack-advertisement"
# Bitbucket's answer per Bearer token on the push discovery; any other token is 401. A 200 that is no Git answer (a
# proxy's login page) is not a confirmation.
ANSWERS = {TOKEN: (200, RECEIVE_PACK), NEW_TOKEN: (200, RECEIVE_PACK), "BBDC-forbidden-0001": (403, None),
           "BBDC-unknown-repo-01": (404, None), "BBDC-login-page-001": (200, "text/html")}


class FakeBitbucket:
    """The IdP (client credentials) and the repository endpoint; every request is recorded."""

    def __init__(self) -> None:
        self.issued = 0
        self.requests: list[httpx.Request] = []

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.url.host == "idp.example.test":
            form = {key: values[0] for key, values in parse_qs(request.content.decode()).items()}
            if form.get("client_secret") != SECRET:
                return httpx.Response(401)
            self.issued += 1
            return httpx.Response(200, json={"access_token": f"tok-{self.issued}", "token_type": "Bearer",
                                             "expires_in": 300})
        if request.url.path == REPO_API and request.url.params.get("service") == "git-receive-pack":
            token = (request.headers.get("Authorization") or "").removeprefix("Bearer ")
            status, content_type = ANSWERS.get(token, (401, None))
            return httpx.Response(status, headers={"content-type": content_type} if content_type else {})
        return httpx.Response(404)

    def token_checks(self) -> list[httpx.Request]:
        return [request for request in self.requests if request.url.path == REPO_API]


@pytest.fixture
def world(monkeypatch):
    """Public DNS; the token check keeps the real ``bitbucket`` egress transport with the fake behind it."""

    async def _resolve(hostname: str, port: int | None):
        return {ipaddress.ip_address("203.0.113.20")}

    async def _no_allowlist(connection: str) -> frozenset[str]:
        return frozenset()

    monkeypatch.setattr("app.services.outbound_url_policy._resolve_hostname_ips", _resolve)
    monkeypatch.setattr("app.services.outbound_egress.target_check._private_host_keys", _no_allowlist)
    oidc_tokens.clear_token_cache()
    fake = FakeBitbucket()

    def pinned(kind, *, inner=None, **kwargs):
        return real_egress_transport(kind, inner=inner or httpx.MockTransport(fake.handle), **kwargs)

    def transport(*_args, inner=None, **_kwargs):
        return inner or httpx.MockTransport(fake.handle)

    monkeypatch.setattr(token_module, "egress_transport", pinned)
    monkeypatch.setattr(listing_module, "egress_transport", transport)
    monkeypatch.setattr(oidc_tokens, "egress_transport", transport)
    yield fake
    oidc_tokens.clear_token_cache()


async def _connection(db, workspaces: list[str]) -> str:
    row = ConnectorNamedConnection(
        id=str(uuid.uuid4()), tool_name="bitbucket", project_id=None, scope_key="global", name="Bitbucket",
        bound_scopes=[], available_in="selected", agent_tools_level="read",
        config={"bitbucket_url": BASE, "bitbucket_deployment": "datacenter",
                "bitbucket_auth_mode": "oidc_client_credentials", "bitbucket_oidc_token_url": IDP,
                "bitbucket_oidc_client_id": "octryx-client"},
    )
    db.add(row)
    await db.flush()
    for workspace_id in workspaces:
        db.add(ConnectionWorkspace(connection_id=row.id, workspace_id=workspace_id))
    stored = await set_secret_value(db, tool_name="bitbucket", project_id=None, value=SECRET,
                                    field_name=named_secret_field("bitbucket_oidc_client_secret", row.id))
    row.config = {**row.config, "bitbucket_oidc_client_secret_secret_ref": stored.id}
    await db.commit()
    return row.id


async def _setup(db) -> tuple[str, str, str]:
    workspace_id = await seed_workspace(db)
    user_id = await seed_member(db, workspace_id=workspace_id, role="admin")
    return workspace_id, user_id, await _connection(db, [workspace_id])


def _url(workspace_id: str, suffix: str = "") -> str:
    return f"/api/v1/workspaces/{workspace_id}/knowledge/connectors/shop{suffix}"


def _body(connection_id: str, **extra) -> dict:
    return {"kind": "git_repository", "fetch_mode": "remote_git", "repository_url": REPO_URL, "ref": "main",
            "connection_id": connection_id, **extra}


async def _audits(db, action: str) -> list[AuditLog]:
    return list((await db.execute(select(AuditLog).where(AuditLog.action == action))).scalars())


async def test_registration_checks_the_token_and_stores_it_encrypted_never_answered(client, db, world) -> None:
    workspace_id, user_id, connection_id = await _setup(db)

    saved = await client.put(_url(workspace_id), headers=bearer(user_id), json=_body(connection_id, git_token=TOKEN))
    assert saved.status_code == 200, saved.text
    state = saved.json()["git_token"]
    assert state["configured"] is True and state["set_by"] == user_id and state["set_at"].endswith("+00:00")
    (check,) = world.token_checks()
    assert check.headers["Authorization"] == f"Bearer {TOKEN}" and check.method == "GET"

    row = (await db.execute(select(RepositoryGitToken))).scalar_one()
    assert (row.project_id, row.host_base, row.repository_key) == (
        workspace_id, BASE, "bitbucket:SHOP/aws-shop-deployment")
    secret = await db.get(StoredSecret, row.secret_id)
    assert TOKEN not in secret.encrypted_value and secret.encrypted_value.startswith("fernet:")
    assert decrypt_secret(secret.encrypted_value) == TOKEN and secret.project_id == workspace_id

    listed = await client.get(f"/api/v1/workspaces/{workspace_id}/knowledge/connectors", headers=bearer(user_id))
    (described,) = listed.json()["connectors"]
    assert described["git_token"] == state
    assert TOKEN not in saved.text + listed.text
    (audit,) = await _audits(db, "knowledge_source.git_token_set")
    assert audit.details["repository_key"] == "bitbucket:SHOP/aws-shop-deployment"
    assert audit.details["replaced"] is False and TOKEN not in json.dumps(audit.details)
    configured = await _audits(db, "knowledge.connector.configure")
    assert TOKEN not in json.dumps([item.details for item in configured])

    resaved = await client.put(_url(workspace_id), headers=bearer(user_id), json=_body(connection_id, ref="develop"))
    assert resaved.json()["git_token"] == state, "a re-save without git_token keeps it"


@pytest.mark.parametrize(("token", "reason"), [
    ("BBDC-not-known-0001", "git_token_invalid"),
    ("short", "git_token_invalid"),
    ("BBDC-forbidden-0001", "git_token_wrong_repository"),
    ("BBDC-unknown-repo-01", "git_token_wrong_repository"),
    ("BBDC-login-page-001", "source_contract_violation"),
])
async def test_a_refused_token_saves_nothing(client, db, world, token, reason) -> None:
    workspace_id, user_id, connection_id = await _setup(db)

    refused = await client.put(_url(workspace_id), headers=bearer(user_id), json=_body(connection_id, git_token=token))
    assert refused.status_code == 409, refused.text
    assert refused.json()["detail"] == {"state": "refused", "reason": reason}
    assert token not in refused.text
    assert (await db.execute(select(KnowledgeSourceConnector))).scalars().all() == []
    assert (await db.execute(select(RepositoryGitToken))).scalars().all() == []
    assert (await db.execute(select(StoredSecret).where(StoredSecret.tool_name == "repository_git_token"))
            ).scalars().all() == []
    assert len(world.token_checks()) == (0 if token == "short" else 1), "a malformed token is never sent"


async def test_a_public_repository_gets_no_git_token(client, db, world) -> None:
    workspace_id, user_id, _ = await _setup(db)
    public = {"kind": "git_repository", "repository_url": "https://github.com/octo/repo", "ref": "main",
              "git_token": TOKEN}
    refused = await client.put(_url(workspace_id), headers=bearer(user_id), json=public)
    assert refused.json()["detail"]["reason"] == "git_token_not_supported" and world.token_checks() == []
    saved = await client.put(_url(workspace_id), headers=bearer(user_id), json={**public, "git_token": None})
    assert saved.status_code == 200 and saved.json()["git_token"] == {"configured": False}
    put = await client.put(_url(workspace_id, "/git-token"), headers=bearer(user_id), json={"git_token": TOKEN})
    assert put.json()["detail"]["reason"] == "git_token_not_supported"


async def test_replace_and_remove_are_audited_and_destroy_the_secret(client, db, world) -> None:
    workspace_id, user_id, connection_id = await _setup(db)
    assert (await client.put(_url(workspace_id), headers=bearer(user_id),
                             json=_body(connection_id, git_token=TOKEN))).status_code == 200
    reader = await seed_member(db, workspace_id=workspace_id, role="member")
    forbidden = await client.put(_url(workspace_id, "/git-token"), headers=bearer(reader), json={"git_token": NEW_TOKEN})
    assert forbidden.status_code == 403

    wrong = await client.put(_url(workspace_id, "/git-token"), headers=bearer(user_id),
                             json={"git_token": "BBDC-unknown-repo-01"})
    assert wrong.json()["detail"]["reason"] == "git_token_wrong_repository"
    replaced = await client.put(_url(workspace_id, "/git-token"), headers=bearer(user_id), json={"git_token": NEW_TOKEN})
    assert replaced.status_code == 200 and replaced.json()["git_token"]["configured"] is True
    assert NEW_TOKEN not in replaced.text
    row = (await db.execute(select(RepositoryGitToken))).scalar_one()
    secret_id = row.secret_id
    assert decrypt_secret((await db.get(StoredSecret, secret_id)).encrypted_value) == NEW_TOKEN
    assert [audit.details["replaced"] for audit in await _audits(db, "knowledge_source.git_token_set")] == [False, True]

    removed = await client.delete(_url(workspace_id, "/git-token"), headers=bearer(user_id))
    assert removed.status_code == 200 and removed.json()["git_token"] == {"configured": False}
    db.expire_all()
    assert (await db.execute(select(RepositoryGitToken))).scalars().all() == []
    assert await db.get(StoredSecret, secret_id) is None
    (audit,) = await _audits(db, "knowledge_source.git_token_removed")
    assert audit.details["reason"] == "removed" and audit.user_id == user_id
    again = await client.delete(_url(workspace_id, "/git-token"), headers=bearer(user_id))
    assert again.status_code == 200 and len(await _audits(db, "knowledge_source.git_token_removed")) == 1


async def test_deleting_the_last_source_of_the_repository_removes_its_token(client, db, world) -> None:
    workspace_id, user_id, connection_id = await _setup(db)
    await client.put(_url(workspace_id), headers=bearer(user_id), json=_body(connection_id, git_token=TOKEN))
    secret_id = (await db.execute(select(RepositoryGitToken))).scalar_one().secret_id

    deleted = await client.delete(_url(workspace_id), headers=bearer(user_id))
    assert deleted.status_code == 200, deleted.text
    db.expire_all()
    assert (await db.execute(select(RepositoryGitToken))).scalars().all() == []
    assert await db.get(StoredSecret, secret_id) is None
    (audit,) = await _audits(db, "knowledge_source.git_token_removed")
    assert audit.details["reason"] == "source_deleted"


async def test_the_token_check_passes_the_bitbucket_egress_rule(world, monkeypatch) -> None:
    async def _private(hostname: str, port: int | None):
        return {ipaddress.ip_address("10.20.30.40")}

    monkeypatch.setattr("app.services.outbound_url_policy._resolve_hostname_ips", _private)
    repository = RepositoryIdentity(BASE, "SHOP/aws-shop-deployment")
    with pytest.raises(ConnectorError) as refused:
        await check_git_token(repository, TOKEN)
    assert refused.value.reason == "egress_refused" and world.requests == [], "nothing leaves for a private host"


async def test_the_token_never_appears_in_a_repr(world) -> None:
    repository = RepositoryIdentity(BASE, "SHOP/aws-shop-deployment")
    checked = await check_git_token(repository, TOKEN)
    credential = resolve_credential(BITBUCKET, {"bitbucket_url": BASE, "bitbucket_auth_mode": "bearer_pat",
                                                "bitbucket_token": "pat-0123456789"})  # gitleaks:allow
    shown = repr(checked) + repr(CheckedGitToken(repository, TOKEN)) + repr(
        ConnectedGitConnection(credential=credential, base_url=BASE, git_token=TOKEN)) + repr(
        GitCloneReader(credential=credential, git_token=TOKEN))
    assert TOKEN not in shown


def _headers(env: dict) -> dict:
    return {env[f"GIT_CONFIG_KEY_{i}"]: env[f"GIT_CONFIG_VALUE_{i}"] for i in range(int(env["GIT_CONFIG_COUNT"]))}


async def _sync_fetch_env(client, db, world, monkeypatch, git_token: str | None) -> dict:
    workspace_id, user_id, connection_id = await _setup(db)
    extra = {"git_token": git_token} if git_token else {}
    saved = await client.put(_url(workspace_id), headers=bearer(user_id), json=_body(connection_id, **extra))
    assert saved.status_code == 200, saved.text
    seen: list[dict] = []

    async def fake_run(argv, env, timeout, max_stdout):
        assert all(TOKEN not in item and "tok-" not in item for item in argv)
        if "fetch" not in argv:
            return 0, b"", b""  # git init of the temporary repository
        seen.append(dict(env))
        return 128, b"", b"fatal: Authentication failed"

    monkeypatch.setattr(git_clone, "run_git", fake_run)
    authorized = await authorize_workspace(db, current_user=await fetch_user(db, user_id), workspace_id=workspace_id)
    runtime, _, _ = build_runtime()
    row = (await db.execute(select(KnowledgeSourceConnector).where(
        KnowledgeSourceConnector.project_id == workspace_id))).scalar_one()
    run = await run_connector(db, runtime=runtime, authorized=authorized, row=row, actor_id=user_id,
                              transport=httpx.MockTransport(world.handle))
    assert (run.state, run.reason) == ("failed", "source_unauthorized")
    assert seen, "git fetched"
    return seen[0]


async def test_the_sync_clones_with_the_repository_token(client, db, world, monkeypatch) -> None:
    env = await _sync_fetch_env(client, db, world, monkeypatch, TOKEN)
    assert _headers(env)["http.https://bitbucket.example.test/.extraHeader"] == f"Authorization: Bearer {TOKEN}"
    assert world.issued == 0, "no OpenID Connect token is requested for Git"


async def test_without_a_repository_token_the_sync_clones_with_the_connections_token(
    client, db, world, monkeypatch
) -> None:
    env = await _sync_fetch_env(client, db, world, monkeypatch, None)
    assert _headers(env)["http.https://bitbucket.example.test/.extraHeader"] == "Authorization: Bearer tok-1"


async def test_the_bitbucket_tools_git_environment_uses_the_workspaces_repository_token(client, db, world) -> None:
    workspace_id, user_id, connection_id = await _setup(db)
    await client.put(_url(workspace_id), headers=bearer(user_id), json=_body(connection_id, git_token=TOKEN))
    other_id = await seed_workspace(db)
    config = {"bitbucket_url": BASE, "bitbucket_auth_mode": "bearer_pat",
              "bitbucket_token": "pat-0123456789"}  # gitleaks:allow

    def context(project_id: str) -> ToolContext:
        return ToolContext(user_id=user_id, project_ids=[project_id], roles=[], session_id="s1",
                           project_config={**config, "project_id": project_id}, db=db)

    run_env = await core._bitbucket_git_auth_env_async(context(workspace_id), CLONE_URL)
    assert run_env["GIT_CONFIG_VALUE_" + str(int(run_env["GIT_CONFIG_COUNT"]) - 1)] == f"Authorization: Bearer {TOKEN}"
    elsewhere = await core._bitbucket_git_auth_env_async(context(other_id), CLONE_URL)
    assert elsewhere["GIT_CONFIG_VALUE_" + str(int(elsewhere["GIT_CONFIG_COUNT"]) - 1)] == (
        "Authorization: Bearer pat-0123456789"), "another Workspace signs in with the connection"
    other_repo = await core._bitbucket_git_auth_env_async(context(workspace_id), f"{BASE}/scm/shop/other.git")
    assert TOKEN not in json.dumps(other_repo), "another repository never gets the token"
