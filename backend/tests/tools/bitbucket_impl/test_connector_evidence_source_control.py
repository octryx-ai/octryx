"""Bitbucket, GitHub and GitLab read tools name each item's page on the configured host."""

from __future__ import annotations

import pytest

from app.tools.bitbucket_impl._bitbucket_evidence import file_url
from app.tools.bitbucket_impl._bitbucket_pull_requests import ListBitbucketPullRequests
from app.tools.bitbucket_impl._bitbucket_repository_base import ListBitbucketRepositories
from app.tools.registry import execute_tool
from tests.connector_evidence_fields_support import _assert_source, _context
from tests.support.tools_github_source_control_support import _create_github_project, _github_context, _pr_payload
from tests.tools.connectors.test_tools_gitlab_source_control import _create_gitlab_project, _gitlab_context, _mr_payload

BITBUCKET = "https://bitbucket.example.test"


# --- Bitbucket --------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_bitbucket_repositories_pull_requests_and_files_name_their_pages(monkeypatch) -> None:
    config = {"bitbucket_url": BITBUCKET, "bitbucket_repositories": [{"project_key": "OPS", "repo_slug": "api"}]}
    monkeypatch.setattr(
        "app.tools.bitbucket_impl._bitbucket_repository_base._normalize_allowed_repos",
        lambda _config: [{"project_key": "OPS", "repo_slug": "api", "enabled": True}],
    )
    repos = await ListBitbucketRepositories().execute({}, _context(**config))
    _assert_source(repos["repositories"][0], f"{BITBUCKET}/projects/OPS/repos/api/browse", title="OPS/api")

    async def fake_get(context, path, params=None):
        return {"values": [{"id": 5, "title": "Fix failover", "links": {"self": [{"href": "x"}]}}]}

    monkeypatch.setattr("app.tools.bitbucket_impl._bitbucket_internal_network._bitbucket_json_get", fake_get)
    monkeypatch.setattr("app.tools.bitbucket_impl._bitbucket_pull_requests._is_repo_allowed", lambda *_args: True)
    listed = await ListBitbucketPullRequests().execute({"project_key": "OPS", "repo_slug": "api"}, _context(**config))
    pr = listed["pull_requests"][0]
    _assert_source(pr, f"{BITBUCKET}/projects/OPS/repos/api/pull-requests/5")

    assert file_url(BITBUCKET, "OPS", "api", "src/Owner.java", "main") == (
        f"{BITBUCKET}/projects/OPS/repos/api/browse/src/Owner.java?at=main"
    )
    assert file_url("", "OPS", "api", "src/Owner.java", None) is None


# --- GitHub / GitLab --------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_github_read_tools_name_their_pages_on_the_configured_host(db, monkeypatch) -> None:
    project_id = await _create_github_project(db)

    async def fake_http_json(method, url, **_kwargs):
        if url.endswith("/pulls"):
            return [_pr_payload(7)]
        if url.endswith("/issues/3"):
            return {"number": 3, "title": "Flaky test", "html_url": "https://github.com/example/octryx/issues/3"}
        if "/contents/" in url:
            return {"content": "", "sha": "b1", "html_url": "https://evil.example/example/octryx/README.md"}
        raise AssertionError(url)

    for module in ("github", "github_issues", "github_source_control"):
        monkeypatch.setattr(f"app.tools.connectors.{module}._http_json", fake_http_json)
    context = _github_context(project_id, db=db)
    repo = {"repository": "example/octryx"}

    listed = await execute_tool("list_github_pull_requests", repo, context)
    _assert_source(listed["pull_requests"][0], "https://github.com/example/octryx/pull/7")
    issue = await execute_tool("get_github_issue", {**repo, "issue_number": "3"}, context)
    _assert_source(issue, "https://github.com/example/octryx/issues/3")
    file = await execute_tool("read_github_file", {**repo, "path": "README.md"}, context)
    assert "source_url" not in file, "an API web URL on a foreign host is never a source"


@pytest.mark.asyncio
async def test_gitlab_read_tools_name_their_pages_on_the_configured_host(db, monkeypatch) -> None:
    project_id = await _create_gitlab_project(db)

    async def fake_http_json(method, url, **_kwargs):
        if url.endswith("/merge_requests"):
            return [_mr_payload(9)]
        if url.endswith("/repository/files/README.md"):
            return {"content": "", "encoding": "base64", "size": 0}
        raise AssertionError(url)

    for module in ("gitlab", "gitlab_merge_requests", "gitlab_source_control"):
        monkeypatch.setattr(f"app.tools.connectors.{module}._http_json", fake_http_json)
    context = _gitlab_context(project_id, db=db)
    project = {"project": "group/octryx"}

    listed = await execute_tool("list_gitlab_merge_requests", project, context)
    _assert_source(listed["merge_requests"][0], "https://gitlab.example/group/octryx/-/merge_requests/9")
    file = await execute_tool("read_gitlab_file", {**project, "path": "README.md", "ref": "main"}, context)
    _assert_source(file, "https://gitlab.example/group/octryx/-/blob/main/README.md")
