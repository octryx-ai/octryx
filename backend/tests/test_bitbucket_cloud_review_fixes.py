"""Review fixes of the Bitbucket Cloud slice (PASS WITH NOTES, findings 1-6), each reproduced first.

1. a pull request id or commit with path segments never reaches a REST path (the allowlist would be bypassed);
2. a Cloud push goes to the clone URL of the bound repository, never the working copy's ``origin``; the token is
   handed only to the connection's own host (Cloud: bitbucket.org; Server/Data Center: its configured host);
3. a requester's Atlassian account binds only on an exact email match (a hidden address is no match);
4. an Inbox link to a pull request is an http(s) page or the run card;
5. a Server-only tool with its own HTTP client (file read, repository bootstrap) refuses a Cloud connection, and a
   Cloud connection whose URL is not bitbucket.org has no credential;
6. a ``local_snapshot`` connector resolves no connection (its run is refused as ``snapshot_upload_required``).
"""

from __future__ import annotations

import pytest

import app.tools.bitbucket_impl._bitbucket_delivery as delivery
import app.tools.bitbucket_impl._bitbucket_internal_network as _bitbucket_internal_network
import app.tools.bitbucket_impl._bitbucket_sync_repo as sync_repo
from app.models import WorkflowRun
from app.services.knowledge.sources.sync.git_cloud import git_repository_connection
from app.services.repository_bootstrap.providers import create_bitbucket_repository
from app.services.workflow_runs.attention import inbox_items
from app.tools.bitbucket_impl._bitbucket_cloud import CloudApiError, cloud_credentials
from app.tools.bitbucket_impl._bitbucket_delivery import AddBitbucketPullRequestComment, GetBitbucketBuildStatuses
from app.tools.bitbucket_impl._bitbucket_internal_core import _bitbucket_git_auth_env_async
from app.tools.bitbucket_impl._bitbucket_repository_base import ReadBitbucketFile
from app.tools.context import ToolContext
from app.tools.jira_impl._jira_user_email import matching_accounts
from tests.knowledge_evidence_seed_support import seed_workspace
from tests.phased_workflow_fixtures import admin_user

CLOUD = {"bitbucket_deployment": "cloud", "bitbucket_url": "https://bitbucket.org", "bitbucket_username": "svc",
         "bitbucket_token": "fake-token",
         "bitbucket_allowed_repos": [{"project_key": "ACME", "repo_slug": "payments", "enabled": True}]}
SERVER = {"bitbucket_url": "https://bb.example.test", "bitbucket_auth_mode": "bearer_pat", "bitbucket_token": "fake-token",
          "bitbucket_allowed_repos": [{"project_key": "P", "repo_slug": "r", "enabled": True}]}


def _context(config: dict, **extra) -> ToolContext:
    return ToolContext(user_id="u", project_ids=["p"], roles=[], session_id=None, project_config=dict(config), **extra)


async def test_1_a_pr_id_or_commit_with_path_segments_never_reaches_a_rest_path(monkeypatch):
    sent: list[str] = []

    async def post(context, path, **kwargs):
        sent.append(path)
        return {"id": 1}, 201

    async def get(context, path, **kwargs):
        sent.append(path)
        return {"values": []}

    async def allowed(*_args, **_kwargs):
        return None

    monkeypatch.setattr(delivery, "_bitbucket_json_post", post)
    monkeypatch.setattr(_bitbucket_internal_network, "_bitbucket_json_get", get)
    monkeypatch.setattr(delivery, "require_project_repository_operation", allowed)
    context = _context(SERVER)
    comment = await AddBitbucketPullRequestComment().execute(
        {"project_key": "P", "repo_slug": "r", "pr_id": "../../../../SECRET/repos/vault/pull-requests/5",
         "text": "x"}, context)
    statuses = await GetBitbucketBuildStatuses().execute(
        {"project_key": "P", "repo_slug": "r", "commit": "../../../api/1.0/projects"}, context)
    assert "error" in comment and "error" in statuses and sent == []


async def test_2_a_cloud_push_goes_to_the_bound_repository_and_the_token_only_to_its_host(monkeypatch, tmp_path):
    with pytest.raises(ValueError):
        await _bitbucket_git_auth_env_async(_context(CLOUD), "https://evil.example.test/acme/payments.git")
    with pytest.raises(ValueError):
        await _bitbucket_git_auth_env_async(_context(SERVER), "https://evil.example.test/scm/P/r.git")
    assert (await _bitbucket_git_auth_env_async(_context(SERVER), "https://bb.example.test/scm/P/r.git"))

    repo = tmp_path / "var" / "repos" / "acme" / "payments"
    (repo / ".git").mkdir(parents=True)
    commands: list[list[str]] = []

    async def git(command, *, cwd=None, timeout_sec=90, env=None):
        commands.append(command)
        answers = {"status": (0, " M calc.py\n", ""), "get-url": (0, "https://evil.example.test/x/y.git\n", ""),
                   "rev-parse": (0, "a" * 40 + "\n", ""), "--show-current": (0, "feature/PAY-1\n", "")}
        return next((answer for key, answer in answers.items() if key in command), (0, "", ""))

    async def allowed(*_args, **_kwargs):
        return None

    monkeypatch.setattr(sync_repo, "_run_git", git)
    monkeypatch.setattr(sync_repo, "require_project_repository_operation", allowed)
    result = await sync_repo.CommitAndPushRepositoryBranch().execute(
        {"project_key": "ACME", "repo_slug": "payments", "local_path": str(repo), "branch_name": "feature/PAY-1",
         "commit_message": "PAY-1: totals"}, _context(CLOUD, workspace_root=str(tmp_path)))
    pushes = [command for command in commands if "push" in command]
    assert pushes and all("https://bitbucket.org/acme/payments.git" in command and "origin" not in command
                          for command in pushes), (result, pushes)
    other = await sync_repo.CommitAndPushRepositoryBranch().execute(
        {"project_key": "OTHER", "repo_slug": "secret", "local_path": str(repo), "branch_name": "feature/PAY-1",
         "commit_message": "x"}, _context(CLOUD, workspace_root=str(tmp_path)))
    assert "error" in other and len([command for command in commands if "push" in command]) == len(pushes)


def test_3_an_atlassian_account_binds_only_on_an_exact_email():
    hidden = {"accountId": "a2", "accountType": "atlassian"}
    assert matching_accounts([hidden], "dev@example.test") == []
    exact = {"accountId": "a1", "emailAddress": "Dev@Example.test", "accountType": "atlassian"}
    assert matching_accounts([hidden, exact], "dev@example.test") == [exact]


async def test_4_an_inbox_pull_request_link_is_an_http_page_or_the_run_card(db):
    admin = await admin_user(db)
    run = WorkflowRun(project_id=await seed_workspace(db), requested_by=admin.id, title="Totals", status="waiting",
                      waiting_kind="watching", workflow_key="k", workflow_kind="phased", context={},
                      pull_request={"provider": "github", "id": "3", "url": "javascript:alert(1)",
                                    "reviewer_skipped": "requester_is_author"})
    db.add(run)
    await db.flush()
    item = next(entry for entry in await inbox_items(db, admin.id) if entry["id"] == run.id)
    assert not str(item["link"].get("href") or "").startswith("javascript:")


async def test_5_server_only_clients_refuse_a_cloud_connection_and_a_foreign_cloud_url_has_no_credential(monkeypatch):
    import httpx

    def no_network(*_args, **_kwargs):
        raise AssertionError("a Cloud connection must not reach a Server REST path")

    monkeypatch.setattr(httpx.AsyncClient, "get", no_network)
    monkeypatch.setattr(httpx.AsyncClient, "post", no_network)
    read = await ReadBitbucketFile().execute({"project_key": "ACME", "repo_slug": "payments", "path": "README.md"},
                                             _context(CLOUD))
    assert "error" in read
    with pytest.raises(ValueError):
        await create_bitbucket_repository(project_config=CLOUD, config={"bitbucket_project_key": "ACME"},
                                          repo_name="new")
    with pytest.raises(CloudApiError):
        await cloud_credentials(_context({**CLOUD, "bitbucket_url": "https://bitbucket.evil.example.test"}))


async def test_6_a_local_snapshot_resolves_no_connection_whatever_its_host(db):
    workspace_id = await seed_workspace(db)
    for remote in ("https://git.example.test/team/tools.git", "https://bitbucket.org/acme/payments.git"):
        connection = await git_repository_connection(db, workspace_id, {"fetch_mode": "local_snapshot",
                                                                         "remote": remote})
        assert getattr(connection, "auth", None) is None
