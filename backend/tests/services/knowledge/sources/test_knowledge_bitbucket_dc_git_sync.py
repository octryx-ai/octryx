"""Syncing a Data Center repository source: the clone carries the OpenID Connect Bearer only in git's environment, also against a real HTTP git server."""

# ruff: noqa: F811  (the shared ``world`` fixture is imported, then requested by name)
from __future__ import annotations

import os
import shutil
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

import httpx
import pytest
from sqlalchemy import select

import app.services.connector_auth.oidc_token_cache as oidc_tokens
import app.services.knowledge.sources.sync.git_clone as git_clone
from app.models.project.knowledge_source_sync import KnowledgeSourceConnector
from app.services.connector_auth.atlassian import resolve_credential
from app.services.connector_auth.atlassian_modes import BITBUCKET
from app.services.knowledge.access.authorization import authorize_workspace
from app.services.knowledge.sources.sync.contract import ConnectorError
from app.services.knowledge.sources.sync.git_clone import GitCloneReader, run_git
from app.services.knowledge.sources.sync.service_run import run_connector
from tests.knowledge_evidence_runtime_support import build_runtime
from tests.knowledge_evidence_seed_support import fetch_user
from tests.policy_engine_support import bearer
from tests.services.knowledge.sources.knowledge_bitbucket_dc_repositories_support import (
    BASE,
    FILES,
    IDP,
    REPO_URL,
    _author,
    _connection,
    _save_body,
)
from tests.services.knowledge.sources.knowledge_bitbucket_dc_support import SECRET, world  # noqa: F401 - fixture


def _git(*args: str, cwd: str | None = None) -> str:
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture
def bare_repo(tmp_path):
    work, bare = tmp_path / "work", tmp_path / "repo.git"
    _git("init", "-q", "-b", "main", str(work))
    for path, data in FILES.items():
        target = work / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    _git("-c", "user.name=t", "-c", "user.email=t@example.test", "add", ".", cwd=str(work))
    _git("-c", "user.name=t", "-c", "user.email=t@example.test", "commit", "-q", "-m", "init", cwd=str(work))
    _git("clone", "-q", "--bare", str(work), str(bare))
    _git("config", "uploadpack.allowAnySHA1InWant", "true", cwd=str(bare))
    return str(bare), _git("rev-parse", "HEAD", cwd=str(work))


class _GitServer(BaseHTTPRequestHandler):
    root = ""
    token = ""
    seen: list[str] = []

    def log_message(self, *_args) -> None:
        return

    def _serve(self) -> None:
        self.seen.append(self.headers.get("Authorization") or "")
        if self.headers.get("Authorization") != f"Bearer {self.token}":
            self.send_response(401)
            self.send_header("WWW-Authenticate", 'Basic realm="git"')
            self.end_headers()
            return
        parts = urlsplit(self.path)
        env = {"PATH": os.environ.get("PATH", ""), "GIT_PROJECT_ROOT": self.root, "GIT_HTTP_EXPORT_ALL": "1",
               "PATH_INFO": parts.path, "QUERY_STRING": parts.query, "REQUEST_METHOD": self.command,
               "CONTENT_TYPE": self.headers.get("Content-Type", ""), "REMOTE_ADDR": "127.0.0.1",
               "GIT_PROTOCOL": self.headers.get("Git-Protocol", "")}
        body = self.rfile.read(int(self.headers.get("Content-Length") or 0)) if self.command == "POST" else b""
        if self.headers.get("Content-Encoding") == "gzip":
            import gzip

            body = gzip.decompress(body)
        out = subprocess.run(["git", "http-backend"], input=body, env=env, capture_output=True, check=False).stdout
        head, _, payload = out.partition(b"\r\n\r\n")
        status = 200
        headers = []
        for line in head.decode().split("\r\n"):
            name, _, value = line.partition(": ")
            if name.lower() == "status":
                status = int(value.split()[0])
            elif name:
                headers.append((name, value))
        self.send_response(status)
        for name, value in headers:
            self.send_header(name, value)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    do_GET = _serve  # noqa: N815 - the http.server handler names
    do_POST = _serve  # noqa: N815 - the http.server handler names


@pytest.fixture
def git_server(bare_repo):
    bare, sha = bare_repo
    root = os.path.dirname(bare)
    handler = type("Handler", (_GitServer,), {"root": root, "token": "tok-1", "seen": []})
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}/repo.git", sha, handler
    server.shutdown()
    shutil.rmtree(root, ignore_errors=True)


async def _no_egress_check(url: str) -> None:
    return None


async def test_a_sync_clones_with_the_bearer_in_gits_environment_only(client, db, world, bare_repo, monkeypatch) -> None:
    bare, sha = bare_repo
    workspace_id, user_id = await _author(db)
    connection_id = await _connection(db, [workspace_id])
    saved = await client.put(f"/api/v1/workspaces/{workspace_id}/knowledge/connectors/shop", headers=bearer(user_id),
                             json=_save_body(connection_id))
    assert saved.status_code == 200, saved.text
    seen: list[tuple[list[str], dict]] = []

    async def fake_run(argv, env, timeout, max_stdout):
        seen.append((list(argv), dict(env)))
        clone_url = f"{BASE}/scm/shop/aws-shop-deployment.git"
        local = [bare if item == clone_url else item for item in argv if item != "protocol.allow=never"]
        local = [item for index, item in enumerate(local) if not (item == "-c" and local[index + 1:index + 2] == ["-c"])]
        return await run_git(local, env, timeout, max_stdout)

    monkeypatch.setattr(git_clone, "run_git", fake_run)
    authorized = await authorize_workspace(db, current_user=await fetch_user(db, user_id), workspace_id=workspace_id)
    runtime, _, evidence_index = build_runtime()

    row = (await db.execute(select(KnowledgeSourceConnector).where(
        KnowledgeSourceConnector.project_id == workspace_id))).scalar_one()
    run = await run_connector(db, runtime=runtime, authorized=authorized, row=row, actor_id=user_id,
                              transport=httpx.MockTransport(world.handle))
    assert run.state == "completed", (run.state, run.reason)
    assert run.report["repository"] == {"ref": "main", "commit": sha}
    fetches = [(argv, env) for argv, env in seen if "fetch" in argv]
    assert fetches and all("tok-1" not in " ".join(argv) for argv, _ in seen)
    _, env = fetches[0]
    headers = {env[f"GIT_CONFIG_KEY_{i}"]: env[f"GIT_CONFIG_VALUE_{i}"] for i in range(int(env["GIT_CONFIG_COUNT"]))}
    assert headers["http.https://bitbucket.example.test/.extraHeader"] == "Authorization: Bearer tok-1"
    assert headers["credential.helper"] == "" and env["GIT_TERMINAL_PROMPT"] == "0" and "GIT_ASKPASS" not in env
    assert "http.followRedirects=false" in fetches[0][0]
    await db.refresh(row)
    assert row.scope["head_commit"] == sha and row.connection_id == connection_id
    from app.services.knowledge.code.codebase import workspace_repositories

    (source,) = await workspace_repositories(db, workspace_id)
    assert source.blob_link("deploy/values.yaml", 2) == f"{REPO_URL}/browse/deploy/values.yaml?at={sha}#L2"


@pytest.mark.skipif(shutil.which("git") is None, reason="git is required")
async def test_git_fetches_from_a_real_server_with_the_oidc_bearer_header(git_server, world) -> None:
    url, sha, handler = git_server
    config = {"bitbucket_url": BASE, "bitbucket_auth_mode": "oidc_client_credentials",
              "bitbucket_oidc_token_url": IDP, "bitbucket_oidc_client_id": "octryx-client",
              "bitbucket_oidc_client_secret": SECRET}
    credential = resolve_credential(BITBUCKET, config)
    argv_seen: list[list[str]] = []

    async def recording_run(argv, env, timeout, max_stdout):
        argv_seen.append(list(argv))
        return await run_git(argv, env, timeout, max_stdout)

    reader = GitCloneReader(credential=credential, egress_check=_no_egress_check, run=recording_run,
                            oidc_transport=httpx.MockTransport(world.idp.handle), protocols=("http",))
    commit, archive = await reader.snapshot(url, ref="main", commit=None, max_bytes=10 * 1024 * 1024)
    assert commit == sha and len(archive) > 0
    assert "Bearer tok-1" in handler.seen and all("tok-1" not in " ".join(argv) for argv in argv_seen)
    again, _ = await reader.snapshot(url, ref="main", commit=sha, max_bytes=10 * 1024 * 1024)
    assert again == sha, "a later page of the same pass fetches the pass's commit"

    handler.token = "another-token"
    oidc_tokens.clear_token_cache()
    with pytest.raises(ConnectorError) as refused:
        await reader.snapshot(url, ref="main", commit=None, max_bytes=10 * 1024 * 1024)
    assert refused.value.reason == "source_unauthorized"
    assert world.idp.issued == 3, "a refused token is renewed and the fetch retried once"
