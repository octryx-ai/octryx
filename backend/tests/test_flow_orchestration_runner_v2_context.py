"""V2 tool argument templates and release and person identity context passed to later nodes."""

import pytest

from app.services.flow_orchestration.runner import execute_flow_version
from tests.flow_orchestration_runner_support import _make_v2_flow_version


@pytest.mark.asyncio
async def test_execute_v2_flow_renders_tool_argument_templates_from_input(db, monkeypatch):
    calls = []

    async def fake_execute_tool(tool_name, params, context):
        calls.append((tool_name, params, context.project_ids))
        return {"query": params["query"], "jql": params.get("jql"), "limit": params["limit"]}

    monkeypatch.setattr("app.services.flow_orchestration.dag.tool_node.execute_tool_with_plugins", fake_execute_tool)
    version = _make_v2_flow_version(
        db,
        "v2-tool-template",
        "f-v2-tool-template",
        "v2-tool-template",
        [
            {
                "id": "input",
                "type": "trigger",
                "output_schema": {"request": "string", "subject_hint": "string"},
            },
            {
                "id": "tool",
                "type": "tool_step",
                "config": {
                    "tool": "search_jira_tickets",
                    "arguments": {
                        "query": "{subject_hint}",
                        "jql": 'summary ~ "{subject_hint}"',
                        "limit": 10,
                    },
                },
            },
            {
                "id": "second-tool",
                "type": "tool_step",
                "config": {
                    "tool": "knowledge_search_by_user",
                    "arguments": {"query": "{subject_hint}", "limit": 5},
                },
            },
            {"id": "out", "type": "output"},
        ],
        [
            {"source_node_id": "input", "target_node_id": "tool"},
            {"source_node_id": "tool", "target_node_id": "second-tool"},
            {"source_node_id": "second-tool", "target_node_id": "out"},
        ],
    )

    run = await execute_flow_version(
        db,
        flow_version_id=version.id,
        user_id="tester",
        project_id="acme-orders",
        initial_input={"request": "Who is Alice Example?", "subject_hint": "Alice Example"},
    )

    assert run.status == "completed"
    assert calls == [
        (
            "search_jira_tickets",
            {"query": "Alice Example", "jql": 'summary ~ "Alice Example"', "limit": 10},
            ["acme-orders"],
        ),
        ("knowledge_search_by_user", {"query": "Alice Example", "limit": 5}, ["acme-orders"]),
    ]


@pytest.mark.asyncio
async def test_execute_v2_flow_propagates_next_release_context_to_jira_issue_search(db, monkeypatch):
    calls = []

    async def fake_execute_tool(tool_name, params, context):
        calls.append((tool_name, params))
        if tool_name == "list_jira_versions":
            return {
                "project_key": "ACME",
                "versions": [
                    {
                        "id": "45348",
                        "name": "shop_2.4.04b",
                        "released": True,
                        "archived": False,
                        "release_date": "2026-04-22",
                        "project_key": "ACME",
                    },
                    {
                        "id": "43290",
                        "name": "shop_2.4.10",
                        "released": False,
                        "archived": False,
                        "release_date": "2026-06-23",
                        "project_key": "ACME",
                    },
                    {
                        "id": "45034",
                        "name": "shop_2.4.20",
                        "released": False,
                        "archived": False,
                        "release_date": None,
                        "project_key": "ACME",
                    },
                ],
            }
        return {
            "jql": params["jql"],
            "total": 2,
            "results": [
                {"key": "ACME-1", "summary": "Release change 1"},
                {"key": "ACME-2", "summary": "Release change 2"},
            ],
        }

    monkeypatch.setattr("app.services.flow_orchestration.dag.tool_node.execute_tool_with_plugins", fake_execute_tool)
    version = _make_v2_flow_version(
        db,
        "v2-release-context",
        "f-v2-release-context",
        "v2-release-context",
        [
            {"id": "input", "type": "trigger", "output_schema": {"request": "string"}},
            {
                "id": "versions",
                "type": "tool_step",
                "config": {"tool": "list_jira_versions", "arguments": {}},
            },
            {
                "id": "changes",
                "type": "tool_step",
                "config": {
                    "tool": "search_jira_tickets",
                    "arguments": {
                        "jql": 'fixVersion = "{release_name}" ORDER BY priority DESC, updated DESC',
                        "limit": 100,
                    },
                },
            },
            {"id": "out", "type": "output"},
        ],
        [
            {"source_node_id": "input", "target_node_id": "versions"},
            {"source_node_id": "versions", "target_node_id": "changes"},
            {"source_node_id": "changes", "target_node_id": "out"},
        ],
    )

    run = await execute_flow_version(
        db,
        flow_version_id=version.id,
        user_id="tester",
        project_id="acme-orders",
        initial_input={"request": "What is the next release and what changes are in this release?"},
    )

    assert run.status == "completed"
    assert calls == [
        ("list_jira_versions", {}),
        (
            "search_jira_tickets",
            {"jql": 'fixVersion = "shop_2.4.10" ORDER BY priority DESC, updated DESC', "limit": 100},
        ),
    ]
    final_result = run.merged_output_json["final"]["result"]
    assert final_result["release_name"] == "shop_2.4.10"
    assert final_result["release_date"] == "2026-06-23"


@pytest.mark.asyncio
async def test_execute_v2_flow_exposes_person_identity_context_to_later_nodes(db, monkeypatch):
    calls = []

    async def fake_execute_tool(tool_name, params, context):
        calls.append((tool_name, params))
        if tool_name == "search_jira_users":
            return {
                "query": params["query"],
                "users": [
                    {
                        "name": "alice",
                        "display_name": "Alice Example",
                        "email": "alice@example.com",
                    }
                ],
                "total": 1,
            }
        if tool_name == "knowledge_search_by_user":
            return {"query": params["query"], "total_matches": 20, "results": []}
        return {"author_filter": params.get("author_aliases"), "total_commit_count": 2}

    monkeypatch.setattr("app.services.flow_orchestration.dag.tool_node.execute_tool_with_plugins", fake_execute_tool)
    version = _make_v2_flow_version(
        db,
        "v2-person-context",
        "f-v2-person-context",
        "v2-person-context",
        [
            {"id": "input", "type": "trigger"},
            {
                "id": "identity",
                "type": "tool_step",
                "config": {"tool": "search_jira_users", "arguments": {"query": "{subject_hint}", "limit": 10}},
            },
            {
                "id": "commits",
                "type": "tool_step",
                "config": {
                    "tool": "list_recent_bitbucket_commits",
                    "arguments": {"author_aliases": "{person_aliases}", "days": 30},
                },
            },
            {
                "id": "work",
                "type": "tool_step",
                "config": {
                    "tool": "knowledge_search_by_user",
                    "arguments": {"query": "{jira_username}", "limit": 5},
                },
            },
            {"id": "out", "type": "output"},
        ],
        [
            {"source_node_id": "input", "target_node_id": "identity"},
            {"source_node_id": "identity", "target_node_id": "work"},
            {"source_node_id": "work", "target_node_id": "commits"},
            {"source_node_id": "commits", "target_node_id": "out"},
        ],
    )

    run = await execute_flow_version(
        db,
        flow_version_id=version.id,
        user_id="tester",
        project_id="acme-orders",
        initial_input={"request": "Who is Alice Example?", "subject_hint": "Alice Example"},
    )

    assert run.status == "completed"
    assert calls[1] == ("knowledge_search_by_user", {"query": "alice", "limit": 5})
    assert calls[2] == (
        "list_recent_bitbucket_commits",
        {"author_aliases": ["Alice Example", "alice", "alice@example.com"], "days": 30},
    )
