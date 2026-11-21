"""Tests for compact tool result formatting and build-within-turn working set messages."""

from app.agent.engine import _compact_tool_result_for_model


def test_compact_tool_result_for_model_for_mcp_bridge():
    servers_compact = _compact_tool_result_for_model(
        "list_mcp_servers",
        {
            "count": 1,
            "servers": [
                {
                    "name": "context7",
                    "vendor": "Upstash",
                    "transport": "stdio",
                    "connected": True,
                    "tool_count": 2,
                    "catalog_slug": "context7",
                }
            ],
        },
    )
    tools_compact = _compact_tool_result_for_model(
        "list_mcp_server_tools",
        {
            "server_name": "context7",
            "connected": True,
            "search": "resolve",
            "count": 1,
            "tools": [
                {
                    "name": "resolve-library-id",
                    "description": "Resolve Context7 library identifiers",
                    "arguments": [
                        {"name": "libraryName", "type": "string", "required": True},
                        {"name": "limit", "type": "integer", "required": False},
                    ],
                }
            ],
        },
    )
    call_compact = _compact_tool_result_for_model(
        "call_mcp_server_tool",
        {
            "server_name": "context7",
            "tool_name": "resolve-library-id",
            "success": True,
            "content": [{"type": "text", "text": "react -> /facebook/react"}],
        },
    )

    assert servers_compact["servers"][0]["name"] == "context7"
    assert tools_compact["tools"][0]["name"] == "resolve-library-id"
    assert call_compact["content"][0]["text"] == "react -> /facebook/react"


def test_compact_tool_result_for_model_for_jira_release_bundle():
    compact = _compact_tool_result_for_model(
        "create_jira_release_bundle",
        {
            "project_key": "ACME",
            "release_name": "ai-release-02",
            "release_date": "2026-04-28",
            "version_id": "45364",
            "version_created": False,
            "release_status": "prepared",
            "release_now": False,
            "created_ticket_count": 2,
            "updated_ticket_count": 0,
            "created_tickets": [
                {
                    "ticket_id": "ACME-471",
                    "summary": "Enhance AWS Monitoring for Stability",
                    "issue_type": "Improvement",
                    "id": "678414",
                }
            ],
        },
    )

    assert compact["release_date"] == "2026-04-28"
    assert compact["created_tickets"][0]["ticket_id"] == "ACME-471"
    assert "id" not in compact["created_tickets"][0]


def test_compact_jira_ticket_search_keeps_ticket_keys_and_user_fields():
    compact = _compact_tool_result_for_model(
        "search_jira_tickets",
        {
            "query": None,
            "jql": 'project in ("ACME") AND assignee in ("alice") ORDER BY updated DESC',
            "api_version": "2",
            "total": 277,
            "results": [
                {
                    "ticket_id": "ACME-544",
                    "summary": "AWS Vulns fix",
                    "status": "In Progress",
                    "assignee": "Alice Example",
                    "reporter": "Rina PM",
                    "creator": "Alice Example",
                    "issue_type": "Task",
                    "created": "2026-01-02T09:00:00.000+0100",
                    "updated": "2026-01-03T10:00:00.000+0100",
                }
            ],
        },
    )

    assert compact["total"] == 277
    assert compact["count"] == 1
    assert compact["results"][0]["ticket_id"] == "ACME-544"
    assert compact["results"][0]["key"] == "ACME-544"
    assert compact["results"][0]["assignee"] == "Alice Example"
    assert compact["results"][0]["creator"] == "Alice Example"
    assert compact["status_counts"] == {"In Progress": 1}
    assert compact["issue_type_counts"] == {"Task": 1}
    assert compact["top_assignees"] == {"Alice Example": 1}


def test_compact_workspace_coding_tools_keep_evidence_without_full_payload():
    file_content = "\n".join(f"resource line {index}" for index in range(400))
    file_compact = _compact_tool_result_for_model(
        "read_workspace_file",
        {
            "path": "/private/var/session/var/repos/bitbucket/SHOP/aws-shop-infrastructure/terraform/base/removed.txt",
            "relative_path": "var/repos/bitbucket/SHOP/aws-shop-infrastructure/terraform/base/removed.txt",
            "content": file_content,
            "size_bytes": len(file_content),
        },
    )

    assert file_compact["relative_path"].endswith("terraform/base/removed.txt")
    assert file_compact["size_bytes"] == len(file_content)
    assert file_compact["returned_line_count"] == 400
    assert len(file_compact["content_excerpt"]) < len(file_content)
    assert file_compact["answer_guidance"]["raw_payload_available_as_artifact"] is True

    directory_compact = _compact_tool_result_for_model(
        "list_workspace_directory",
        {
            "path": "/private/var/session/repo",
            "relative_path": "var/repos/bitbucket/SHOP/repo",
            "count": 2,
            "entries": [
                {"name": "terraform", "path": "/private/var/session/repo/terraform", "type": "directory"},
                {
                    "name": "README.md",
                    "path": "/private/var/session/repo/README.md",
                    "relative_path": "var/repos/bitbucket/SHOP/repo/README.md",
                    "type": "file",
                },
            ],
        },
    )

    assert directory_compact["returned_count"] == 2
    assert directory_compact["entries"][0]["relative_path"].endswith("repo/terraform")


def test_compact_repository_jira_and_pr_tools_keep_navigation_context():
    repo_compact = _compact_tool_result_for_model(
        "prepare_bitbucket_repository",
        {
            "project_key": "SHOP",
            "repo_slug": "aws-shop-infrastructure",
            "repository_url": "https://scm.example.test/bitbucket/projects/SHOP/repos/aws-shop-infrastructure/browse",
            "branch_name": "feature/ACME-615-clean-base-terraform-leftovers",
            "local_path": "/private/var/session/var/repos/bitbucket/SHOP/aws-shop-infrastructure",
            "relative_path": "var/repos/bitbucket/SHOP/aws-shop-infrastructure",
        },
    )

    assert repo_compact["project_key"] == "SHOP"
    assert repo_compact["relative_path"].endswith("aws-shop-infrastructure")
    assert repo_compact["answer_guidance"]["use_relative_path_for_workspace_tools"] is True

    jira_compact = _compact_tool_result_for_model(
        "get_jira_ticket",
        {
            "key": "ACME-615",
            "url": "https://jira.example.test/jira/browse/ACME-615",
            "summary": "Cleaning Terraform and Helm Config",
            "description": "Clean first terraform after the pipeline split.",
            "status": {"name": "Open"},
            "labels": ["octryx"],
            "fixVersions": [{"name": "shop_2.4.10"}],
        },
    )

    assert jira_compact["key"] == "ACME-615"
    assert jira_compact["url"].endswith("/ACME-615")
    assert jira_compact["status"] == "Open"
    assert jira_compact["fix_versions"] == ["shop_2.4.10"]

    pr_compact = _compact_tool_result_for_model(
        "get_bitbucket_pull_request",
        {
            "id": 672,
            "title": "ACME-615 cleanup",
            "state": "DECLINED",
            "links": {
                "self": [
                    {
                        "href": "https://scm.example.test/bitbucket/projects/SHOP/repos/aws-shop-infrastructure/pull-requests/672"
                    }
                ]
            },
            "reviewers": [{"user": {"displayName": "Reviewer One"}, "status": "UNAPPROVED", "approved": False}],
        },
    )

    assert pr_compact["id"] == 672
    assert pr_compact["state"] == "DECLINED"
    assert pr_compact["url"].endswith("/pull-requests/672")
    assert pr_compact["answer_guidance"]["declined_pull_requests_are_not_implementation_success"] is True
