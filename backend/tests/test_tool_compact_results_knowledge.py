"""Compacting workflow capability, Bitbucket commit list and repository knowledge results without losing evidence or coordinates."""

from app.agent.engine import _compact_tool_result_for_model


def test_compact_workflow_capability_result_keeps_evidence_for_answering():
    compact = _compact_tool_result_for_model(
        "run_flow_person_source_evidence_research",
        {
            "workflow_capability": {
                "tool_name": "run_flow_person_source_evidence_research",
                "name": "Person Source-Evidence Research",
                "version": 3,
                "flow_id": "flow-1",
                "version_id": "version-1",
            },
            "flow_run": {
                "id": "run-1",
                "status": "completed",
                "pattern_type": "sequential",
                "project_id": "project-1",
                "total_steps": 7,
                "merged_output_json": {"nodes": {"too": "large"}},
            },
            "evidence_summary": {
                "observations": [
                    {
                        "node_id": "search-jira-user",
                        "tool": "search_jira_users",
                        "total": 1,
                        "user_examples": [{"name": "alice", "display_name": "Alice Example"}],
                    },
                    {
                        "node_id": "search-jira-work",
                        "tool": "search_jira_tickets",
                        "jql": 'project in ("ACME") AND assignee in ("alice")',
                        "total": 277,
                        "result_examples": [{"key": "ACME-544", "summary": "AWS Vulns fix"}],
                    },
                ],
                "answer_guidance": ["Use only the tools and evidence listed in observations."],
            },
            "result": {"nodes": {str(index): {"payload": "x" * 500} for index in range(100)}},
        },
    )

    assert compact["workflow_capability"]["tool_name"] == "run_flow_person_source_evidence_research"
    assert compact["flow_run"]["status"] == "completed"
    assert compact["evidence_summary"]["observations"][0]["user_examples"][0]["name"] == "alice"
    assert compact["evidence_summary"]["observations"][1]["total"] == 277
    assert "merged_output_json" not in compact["flow_run"]
    assert any("Do not invent" in item for item in compact["evidence_summary"]["answer_guidance"])


def test_compact_workflow_capability_result_keeps_release_context_for_answering():
    compact = _compact_tool_result_for_model(
        "run_flow_release_status_research",
        {
            "workflow_capability": {
                "tool_name": "run_flow_release_status_research",
                "name": "Release Status Research",
                "version": 1,
                "flow_id": "flow-1",
                "version_id": "version-1",
            },
            "flow_run": {"id": "run-1", "status": "completed"},
            "evidence_summary": {
                "release_context": {
                    "release_name": "shop_2.4.10",
                    "release_date": "2026-06-23",
                    "release_project_key": "ACME",
                },
                "observations": [
                    {
                        "node_id": "load-release-changes",
                        "tool": "search_jira_tickets",
                        "total": 27,
                        "result_examples": [
                            {"ticket_id": "ACME-204", "summary": "Deploy checkout pilot changes"},
                        ],
                    }
                ],
            },
        },
    )

    assert compact["workflow_capability"]["tool_name"] == "run_flow_release_status_research"
    assert compact["evidence_summary"]["release_context"]["release_name"] == "shop_2.4.10"
    assert compact["evidence_summary"]["release_context"]["release_date"] == "2026-06-23"
    assert compact["evidence_summary"]["observations"][0]["total"] == 27


def test_compact_bitbucket_result_summarizes_commit_list_for_model():
    result = {
        "days": 1,
        "cutoff_utc": "2026-03-24T00:00:00+00:00",
        "total_commit_count": 42,
        "repositories": [
            {
                "project_key": "SHOP",
                "repo_slug": "acme-orders",
                "label": "SHOP/acme-orders",
                "commit_count": 42,
                "commits": [
                    {
                        "project_key": "SHOP",
                        "repo_slug": "acme-orders",
                        "repository_label": "SHOP/acme-orders",
                        "display_id": f"abc{i:03d}",
                        "message": f"Commit {i}",
                        "author_name": "Alice",
                        "author_timestamp": 1000 + i,
                    }
                    for i in range(42)
                ],
            }
        ],
        "commits": [
            {
                "project_key": "SHOP",
                "repo_slug": "acme-orders",
                "repository_label": "SHOP/acme-orders",
                "display_id": f"abc{i:03d}",
                "message": f"Commit {i}",
                "author_name": "Alice",
                "author_timestamp": 1000 + i,
            }
            for i in range(42)
        ],
    }

    compacted = _compact_tool_result_for_model("list_recent_bitbucket_commits", result)

    assert compacted["total_commit_count"] == 42
    assert compacted["repository_count"] == 1
    assert compacted["branch_mode"] is None
    assert len(compacted["recent_commits"]) == 12
    assert len(compacted["repositories"]) == 1
    assert len(compacted["repositories"][0]["recent_commits"]) == 3
    assert compacted["repository_commit_counts"] == {"SHOP/acme-orders": 42}
    assert compacted["author_counts"] == {"Alice": 42}


def test_compact_project_knowledge_does_not_silently_truncate_entries_or_keys():
    result = {
        "project_name": "acme-orders",
        "count": 28,
        "query": "report-builder",
        "tags": ["tooling"],
        "entries": [
            {
                "category": "architecture",
                "key": f"report-builder-{i}",
                "tags": ["tooling", "report-builder"],
                "source": "confluence",
                "value": {"summary": f"Entry {i}"},
            }
            for i in range(28)
        ],
    }
    compacted = _compact_tool_result_for_model("list_project_knowledge", result)

    assert compacted["count"] == 28
    assert len(compacted["entries"]) == 28
    assert compacted["entries"][-1]["key"] == "report-builder-27"

    keys_result = {
        "project_name": "acme-orders",
        "count": 57,
        "query": "report-builder",
        "tags": ["tooling"],
        "keys": [
            {
                "category": "architecture",
                "key": f"report-builder-key-{i}",
                "tags": ["tooling"],
                "version": i,
            }
            for i in range(57)
        ],
    }
    compacted_keys = _compact_tool_result_for_model("list_project_knowledge_keys", keys_result)

    assert compacted_keys["count"] == 57
    assert len(compacted_keys["keys"]) == 57
    assert compacted_keys["keys"][-1]["key"] == "report-builder-key-56"


def test_compact_plan_bitbucket_knowledge_sync_keeps_repo_coordinates():
    result = {
        "project_name": "acme-orders",
        "repository_count": 1,
        "changed_repository_count": 1,
        "repositories": [
            {
                "project_key": "SHOP",
                "repo_slug": "acme-orders-stack",
                "label": "SHOP/acme-orders-stack",
                "branch_name": "master",
                "current_head_commit": "head999",
                "last_synced_commit": "old123",
                "requires_sync": True,
                "sync_reason": "head_changed",
                "matched_previous_commit": True,
                "recent_commits": [
                    {"display_id": "head999", "message": "Update values", "author_timestamp": 1700001000000}
                ],
                "interesting_paths": ["README.md", "charts/values.yaml"],
            }
        ],
    }

    compacted = _compact_tool_result_for_model("plan_bitbucket_knowledge_sync", result)

    assert compacted["repositories"][0]["project_key"] == "SHOP"
    assert compacted["repositories"][0]["repo_slug"] == "acme-orders-stack"
    assert compacted["repositories"][0]["branch_name"] == "master"


def test_compact_collect_repository_knowledge_sources_keeps_repo_coordinates():
    result = {
        "count": 1,
        "summary": "Collected knowledge sources for 1 repositories.",
        "repositories": [
            {
                "project_key": "SHOP",
                "repo_slug": "acme-orders-stack",
                "label": "SHOP/acme-orders-stack",
                "branch_name": "master",
                "current_head_commit": "head999",
                "last_synced_commit": None,
                "source_mode": "readme",
                "missing_readme_total": 0,
                "existing_readme_paths": ["var/repos/bitbucket/SHOP/acme-orders-stack/README.md"],
                "top_level_directories": ["charts", "deployments"],
                "build_files": [{"relative_to_repo": "pom.xml", "kind": "maven"}],
                "source_files": [
                    {
                        "path": "var/repos/bitbucket/SHOP/acme-orders-stack/README.md",
                        "reason": "root_readme",
                        "excerpt": "README excerpt",
                    }
                ],
            }
        ],
    }

    compacted = _compact_tool_result_for_model("collect_repository_knowledge_sources", result)

    assert compacted["repositories"][0]["project_key"] == "SHOP"
    assert compacted["repositories"][0]["repo_slug"] == "acme-orders-stack"
    assert compacted["repositories"][0]["source_files"][0]["path"].endswith("README.md")
