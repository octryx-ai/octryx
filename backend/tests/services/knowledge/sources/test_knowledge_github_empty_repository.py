"""A GitHub repository without files is no failure: an empty tree is an empty snapshot, a repository without
commits is ``repository_empty``, and a token reads only inside the connection's ``knowledge`` scope."""

# ruff: noqa: F811  (the shared ``dns`` fixture is imported, then requested by name)
from __future__ import annotations

import io
import tarfile
import uuid

import httpx
import pytest

from app.models import ConnectionDeviation, ConnectorNamedConnection
from app.models.project.knowledge_source_sync import KnowledgeSourceConnector
from app.services.knowledge.access.authorization import authorize_workspace
from app.services.knowledge.sources.sync.config import validate_config
from app.services.knowledge.sources.sync.git_cloud import ConnectedGitConnection
from app.services.knowledge.sources.sync.git_config import GitScope
from app.services.knowledge.sources.sync.git_repository import GitRepositoryConnector
from app.services.knowledge.sources.sync.scope_connections import resolve_scope_connections
from app.services.knowledge.sources.sync.service import configure_connector
from app.services.knowledge.sources.sync.service_run import run_connector
from app.services.named_connections.contract import named_secret_field
from app.services.secret import set_secret_value
from app.services.secure_work.repositories.knowledge_source import bind_source, source_catalog
from app.services.workflow_routing.phased_start_repository import repository_options
from tests.knowledge_evidence_runtime_support import build_runtime
from tests.knowledge_evidence_seed_support import fetch_user, seed_member, seed_workspace
from tests.services.knowledge.sources.knowledge_github_support import dns  # noqa: F401 - fixture

OWNER, REPO = "octryx-ai", "bench"
SHA = "a1" * 20
TOKEN = "fake-github-token"


def _tarball(files: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as tar:
        top = tarfile.TarInfo(f"{OWNER}-{REPO}-{SHA[:7]}")
        top.type = tarfile.DIRTYPE
        tar.addfile(top)
        for path, data in files.items():
            info = tarfile.TarInfo(f"{top.name}/{path}")
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return buffer.getvalue()


class FakeGitHub:
    def __init__(self, *, files: dict[str, bytes] | None, commit_status: int = 200, empty_archive: bool = False,
                 private: bool = False) -> None:
        self.files, self.commit_status, self.empty_archive, self.private = files, commit_status, empty_archive, private
        self.requests: list[tuple[str, str, str | None]] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        auth = request.headers.get("authorization")
        self.requests.append((request.url.host, request.url.path, auth))
        host, path = request.url.host, request.url.path
        if host != "api.github.com":
            assert auth is None, "the token goes to api.github.com only"
        if self.files is None or (self.private and host == "api.github.com" and auth != f"Bearer {TOKEN}"):
            return httpx.Response(404)
        base = f"/repos/{OWNER}/{REPO}"
        if host == "api.github.com" and path == f"{base}/commits/main":
            return httpx.Response(self.commit_status, text=SHA if self.commit_status == 200 else "{}")
        if host == "api.github.com" and path == f"{base}/git/trees/{SHA}":
            entries = [{"path": name, "type": "blob"} for name in self.files]
            return httpx.Response(200, json={"sha": "t" * 40, "tree": entries, "truncated": False})
        if host == "api.github.com" and path == f"{base}/tarball/{SHA}":
            return httpx.Response(302, headers={"location": f"https://codeload.github.com/{OWNER}/{REPO}/legacy.tar.gz/"
                                                            f"{SHA}?token=short-lived"})
        if host == "codeload.github.com" and (path == f"/{OWNER}/{REPO}/tar.gz/{SHA}"
                                              or path == f"/{OWNER}/{REPO}/legacy.tar.gz/{SHA}"):
            if self.private and "token=" not in str(request.url):
                return httpx.Response(404)
            if not self.files and not self.empty_archive:
                return httpx.Response(404)
            return httpx.Response(200, content=_tarball(self.files))
        return httpx.Response(404)


async def _sync(db, github: FakeGitHub, **config):
    workspace_id = await seed_workspace(db)
    user_id = await seed_member(db, workspace_id=workspace_id, role="admin")
    authorized = await authorize_workspace(db, current_user=await fetch_user(db, user_id), workspace_id=workspace_id)
    runtime, _, evidence_index = build_runtime()
    values = {"repository_url": f"https://github.com/{OWNER}/{REPO}", "ref": "main", "fetch_mode": "remote_git",
              **config}
    row = await configure_connector(db, authorized=authorized, actor_id=user_id,
                                    config=validate_config(connector_key="bench", kind="git_repository", **values))
    run = await run_connector(db, runtime=runtime, authorized=authorized, row=row, actor_id=user_id,
                              transport=httpx.MockTransport(github.handler))
    return authorized, user_id, run, await db.get(KnowledgeSourceConnector, row.id)


@pytest.mark.parametrize("empty_archive", [False, True], ids=["archive_404", "archive_without_files"])
async def test_a_commit_without_files_is_an_empty_snapshot_the_source_and_a_run_can_use(db, dns, empty_archive):
    authorized, user_id, run, row = await _sync(db, FakeGitHub(files={}, empty_archive=empty_archive))

    assert (run.state, run.reason) == ("completed", None)
    assert run.report["created"] == 0 and run.report["failed"] == 0
    assert run.report["repository"] == {"ref": "main", "commit": SHA}
    assert row.scope["head_commit"] == SHA and row.scope["head_dirty"] is False

    # What the Repositories page reads for "Set up code navigation" (repositoryPresenter: canSetUp = source.commit).
    [source] = (await source_catalog(db, authorized))["items"]
    assert source["commit"] == SHA and source["last_sync"] == {"state": "completed", "reason": None}

    bound = await bind_source(db, authorized, user_id, row.id)
    [option] = await repository_options(db, authorized.project_id)
    assert option["id"] == bound["repository_id"] and option["ref"] == f"github:{OWNER}/{REPO}"


async def test_a_repository_without_any_commit_completes_as_repository_empty(db, dns) -> None:
    _, _, run, row = await _sync(db, FakeGitHub(files={}, commit_status=409))

    assert (run.state, run.reason) == ("completed", "repository_empty")
    assert run.report["created"] == 0 and run.report["repository"]["empty"] is True
    assert "head_commit" not in row.scope


async def test_an_include_filter_matching_no_file_is_no_failure(db, dns) -> None:
    files = {"README.md": b"# Bench\n", "tea/web/app.py": b"print('tea')\n"}
    _, _, run, row = await _sync(db, FakeGitHub(files=files), include_globs=["coffee/web/claude/**"])

    assert (run.state, run.reason) == ("completed", None)
    assert run.report["created"] == 0 and row.scope["head_commit"] == SHA


@pytest.mark.parametrize(("github", "reason"), [
    (FakeGitHub(files=None), "source_not_found"),  # no such repository (or not visible to the reader)
    (FakeGitHub(files={"a.py": b"x = 1\n"}, commit_status=422), "source_not_found"),  # other refs, not "main"
], ids=["missing_repository", "unknown_ref"])
async def test_a_missing_repository_or_ref_still_fails(db, dns, github, reason) -> None:
    _, _, run, row = await _sync(db, github)

    assert (run.state, run.reason) == ("failed", reason)
    assert "head_commit" not in row.scope


async def test_a_private_repository_reads_with_the_connection_token_on_the_api_only(db, dns) -> None:
    github = FakeGitHub(files={"README.md": b"# Bench\n"}, private=True)
    scope = GitScope.load(validate_config(connector_key="bench", kind="git_repository",
                                          repository_url=f"https://github.com/{OWNER}/{REPO}", ref="main",
                                          fetch_mode="remote_git").scope)
    connector = GitRepositoryConnector(scope, transport=httpx.MockTransport(github.handler), bearer=TOKEN)

    page = await connector.list_items(None, limit=10)

    assert [item.title for item in page.items] == [f"{REPO}:README.md"] and connector.commit == SHA
    assert [(host, auth is not None) for host, _, auth in github.requests] == [
        ("api.github.com", True), ("api.github.com", True), ("codeload.github.com", False)]

    anonymous = GitRepositoryConnector(scope, transport=httpx.MockTransport(github.handler))
    with pytest.raises(Exception) as hidden:
        await anonymous.list_items(None, limit=10)
    assert getattr(hidden.value, "reason", None) == "source_not_found"


async def test_a_source_linked_to_a_github_connection_with_a_token_gets_it(db) -> None:
    workspace_id = await seed_workspace(db)
    remote = {"remote": f"https://github.com/{OWNER}/{REPO}", "fetch_mode": "remote_git"}

    connection = _github_connection_factory(db, workspace_id)
    token = await connection({"github_owner": OWNER})
    enterprise = await connection({"github_owner": OWNER, "github_url": "https://github.example.com/api/v3"})

    scoped = await resolve_scope_connections(db, kind="git_repository", project_id=workspace_id, scope=dict(remote),
                                             connection_id=token.id)
    assert isinstance(scoped.single, ConnectedGitConnection) and scoped.single.bearer == TOKEN
    assert TOKEN not in repr(scoped.single)
    with pytest.raises(Exception) as other_github:
        await resolve_scope_connections(db, kind="git_repository", project_id=workspace_id, scope=dict(remote),
                                        connection_id=enterprise.id)
    assert getattr(other_github.value, "reason", None) == "connection_pin_mismatch"


@pytest.mark.parametrize(("entries", "reason"), [
    (["Octryx-AI"], None),  # an owner entry covers every repository of the owner, in any case
    ([f"{OWNER}/{REPO}"], None),  # exactly this repository
    ([f"{OWNER}/other", "someone-else"], "scope_not_allowed"),  # another repository, another owner
    ([], "scope_not_allowed"),  # an empty scope admits nothing (deviation_refusal, as for Bitbucket)
    (None, None),  # no scope: unrestricted
], ids=["owner", "exact_repository", "other", "empty", "unset"])
async def test_the_token_reads_only_repositories_inside_the_knowledge_scope(db, entries, reason) -> None:
    workspace_id = await seed_workspace(db)
    row = await _github_connection_factory(db, workspace_id)({"github_owner": OWNER})
    knowledge = {} if entries is None else {"scope": {"repositories": entries}}
    db.add(ConnectionDeviation(connection_id=row.id, workspace_id=workspace_id, fields={"knowledge": knowledge}))
    await db.flush()
    remote = {"remote": f"https://github.com/{OWNER}/{REPO}", "fetch_mode": "remote_git"}

    try:
        scoped = await resolve_scope_connections(db, kind="git_repository", project_id=workspace_id,
                                                 scope=dict(remote), connection_id=row.id)
    except Exception as error:  # noqa: BLE001 - the refusal's fixed reason is the assertion
        assert getattr(error, "reason", None) == reason
    else:
        assert reason is None and scoped.single.bearer == TOKEN


def _github_connection_factory(db, workspace_id: str):
    async def connection(config: dict) -> ConnectorNamedConnection:
        row = ConnectorNamedConnection(id=str(uuid.uuid4()), tool_name="github", project_id=None,
                                       scope_key="global", name=f"gh-{uuid.uuid4().hex[:4]}",
                                       bound_scopes=[OWNER], config=config, available_in="selected",
                                       owner_kind="workspace", owner_workspace_id=workspace_id)
        db.add(row)
        await db.flush()
        stored = await set_secret_value(db, tool_name="github", field_name=named_secret_field("github_token", row.id),
                                        project_id=None, value=TOKEN)
        row.config = {**config, "github_token_secret_ref": stored.id}
        await db.flush()
        return row

    return connection
