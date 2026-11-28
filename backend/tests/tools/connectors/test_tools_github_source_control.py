"""The provider-owned GitHub read tools for branches, pull requests and issues are bound to the repository policy."""

from __future__ import annotations

import base64
from typing import Any

import pytest

from app.tools.registry import execute_tool
from tests.support.tools_github_source_control_support import _create_github_project, _github_context, _pr_payload


def _issue_payload(number: int = 5, *, title: str = "Issue title") -> dict[str, Any]:
    return {
        "number": number,
        "title": title,
        "state": "open",
        "user": {"login": "alice"},
        "assignees": [{"login": "reviewer"}],
        "labels": [{"name": "backend"}],
        "created_at": "2026-07-02T00:00:00Z",
        "updated_at": "2026-07-02T00:00:00Z",
        "closed_at": None,
        "html_url": f"https://github.com/example/octryx/issues/{number}",
        "body": "Issue body",
    }


def _fake_github_http_json(http_calls: list):
    async def fake_http_json(method, url, *, headers=None, params=None, json_body=None, timeout=30):
        assert headers["Authorization"] == "Bearer gh-token"
        assert "gh-token" not in url
        http_calls.append((method, url, json_body))
        if method == "GET" and url.endswith("/contents/README.md"):
            return {
                "content": base64.b64encode(b"hello github").decode("ascii"),
                "encoding": "base64",
                "size": 12,
                "sha": "file-sha",
            }
        if method == "GET" and url.endswith("/branches"):
            return [{"name": "main", "commit": {"sha": "main-sha"}, "protected": True}]
        if method == "GET" and url.endswith("/git/ref/heads/main"):
            return {"object": {"sha": "main-sha"}}
        if method == "POST" and url.endswith("/git/refs"):
            assert json_body == {"ref": "refs/heads/codex/test", "sha": "main-sha"}
            return {"ref": "refs/heads/codex/test"}
        if method == "GET" and url.endswith("/pulls"):
            return [_pr_payload()]
        if method == "GET" and url.endswith("/pulls/7"):
            return _pr_payload()
        if method == "POST" and url.endswith("/pulls"):
            assert json_body == {
                "title": "PR title",
                "head": "codex/test",
                "base": "main",
                "body": "PR body",
            }
            return _pr_payload()
        if method == "PATCH" and url.endswith("/pulls/7"):
            assert json_body == {"body": "Updated", "base": "develop"}
            return _pr_payload(title="PR title", base="develop")
        if method == "GET" and url.endswith("/issues"):
            return [_issue_payload(), {**_issue_payload(number=6), "pull_request": {}}]
        if method == "POST" and url.endswith("/issues"):
            assert json_body["title"] == "Issue title"
            assert json_body["labels"] == ["backend"]
            return _issue_payload()
        if method == "PATCH" and url.endswith("/issues/5"):
            assert json_body == {"state": "closed"}
            return _issue_payload(title="Issue title")
        raise AssertionError(f"unexpected GitHub request: {method} {url}")

    return fake_http_json


def _patch_github_http(monkeypatch, fake_http_json) -> None:
    monkeypatch.setattr("app.tools.connectors.github_source_control._http_json", fake_http_json)
    monkeypatch.setattr("app.tools.connectors.github_pull_requests._http_json", fake_http_json)
    monkeypatch.setattr("app.tools.connectors.github_issues._http_json", fake_http_json)
    monkeypatch.setattr("app.tools.connectors.github._http_json", fake_http_json)


async def _run_pull_request_tools(context) -> tuple[dict, dict, dict, dict]:
    pr_result = await execute_tool(
        "create_github_pull_request",
        {
            "repository": "example/octryx",
            "title": "PR title",
            "from_branch": "codex/test",
            "to_branch": "main",
            "description": "PR body",
        },
        context,
    )
    list_pr_result = await execute_tool(
        "list_github_pull_requests", {"repository": "example/octryx"}, context
    )
    get_pr_result = await execute_tool(
        "get_github_pull_request", {"repository": "example/octryx", "pr_number": 7}, context
    )
    update_pr_result = await execute_tool(
        "update_github_pull_request",
        {"repository": "example/octryx", "pr_number": 7, "description": "Updated", "to_branch": "develop"},
        context,
    )
    return pr_result, list_pr_result, get_pr_result, update_pr_result


@pytest.mark.asyncio
async def test_github_provider_owned_read_branch_pr_and_issue_tools_are_policy_bound(db, monkeypatch):
    project_id = await _create_github_project(db)
    http_calls: list[tuple[str, str, dict[str, Any] | None]] = []

    fake_http_json = _fake_github_http_json(http_calls)
    _patch_github_http(monkeypatch, fake_http_json)

    context = _github_context(project_id, db=db)
    read_result = await execute_tool("read_github_file", {"repository": "example/octryx", "path": "README.md"}, context)
    branches_result = await execute_tool("list_github_branches", {"repository": "example/octryx"}, context)
    branch_result = await execute_tool(
        "create_github_branch",
        {"repository": "example/octryx", "branch_name": "codex/test", "start_point": "main"},
        context,
    )
    pr_result, list_pr_result, get_pr_result, update_pr_result = await _run_pull_request_tools(context)
    issues_result = await execute_tool("list_github_issues", {"repository": "example/octryx"}, context)
    issue_result = await execute_tool(
        "create_github_issue",
        {"repository": "example/octryx", "title": "Issue title", "labels": ["backend"]},
        context,
    )
    update_issue_result = await execute_tool(
        "update_github_issue", {"repository": "example/octryx", "issue_number": 5, "state": "closed"}, context
    )

    assert read_result["content"] == "hello github"
    assert read_result["source_control"]["operation"] == "read_file"
    assert branches_result["source_control"]["operation"] == "list_branches"
    assert branch_result["source_control"]["operation"] == "create_branch"
    assert pr_result["source_control"]["operation"] == "create_change_request"
    assert "source_control" in list_pr_result, list_pr_result
    assert list_pr_result["source_control"]["operation"] == "list_change_requests"
    assert get_pr_result["source_control"]["operation"] == "get_change_request"
    assert update_pr_result["source_control"]["operation"] == "update_change_request"
    assert issues_result["count"] == 1
    assert issue_result["status"] == "created"
    assert update_issue_result["status"] == "updated"
    safe_payload = str(
        {
            "read": read_result.get("source_control"),
            "branch": branch_result.get("source_control"),
            "pr": pr_result.get("source_control"),
            "update_pr": update_pr_result.get("source_control"),
            "issues": issues_result,
        }
    ).lower()
    assert "gh-token" not in safe_payload
    assert "authorization" not in safe_payload
    assert http_calls
