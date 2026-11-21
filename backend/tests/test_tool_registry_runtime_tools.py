"""Code search and impact analysis provenance, summary domain coverage, turn diff tracking and the system prompt."""

from pathlib import Path

import pytest

from app.agent.core.guards.summary_domains import summary_domains_satisfied_by_result
from app.agent.core.prompts.prompt_builder import build_system_prompt
from app.agent.core.turn.turn_diff import TurnDiffTracker
from app.tools.context import ToolContext
from app.tools.registry import get_all_tools_with_plugins
from app.tools.runtime_impl._runtime_code import CodeImpactAnalysisTool, CodeSearchRepositoryTool


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_code_search_tool_adds_provenance(monkeypatch, tmp_path: Path):
    async def fake_search_repository_code(**kwargs):
        return {
            "repository": {"id": "repo-1", "effective_backends": {"index": "zoekt", "semantic": "regex"}},
            "query": "helper",
            "search_backend": "zoekt",
            "text_matches": [{"path": "src/app.py", "line": 1, "column": 5, "preview": "def helper():"}],
            "symbol_matches": [],
            "total_text_matches": 1,
            "total_symbol_matches": 0,
            "engines": {"index_backend": "zoekt", "semantic_backend": "regex"},
        }

    monkeypatch.setattr("app.services.code_intelligence.queries.search_repository_code", fake_search_repository_code)
    tool = CodeSearchRepositoryTool()
    context = ToolContext(
        user_id="test-user",
        project_ids=[],
        roles=["developer"],
        session_id="session-1",
        project_config={},
        workspace_root=str(tmp_path),
        db=None,
    )

    result = await tool.execute({"query": "helper"}, context)

    assert result["provenance"]["search_backend"] == "zoekt"
    assert result["provenance"]["repository_effective_backends"]["index"] == "zoekt"
    assert result["provenance"]["snapshot_engines"]["index_backend"] == "zoekt"


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_code_impact_analysis_tool_adds_definition_and_reference_provenance(monkeypatch, tmp_path: Path):
    async def fake_build_impact_analysis(**kwargs):
        return {
            "repository": {"id": "repo-1", "effective_backends": {"index": "ripgrep", "semantic": "scip"}},
            "symbol": "helper",
            "definitions": [{"path": "src/app.py", "line": 1, "backend": "lsp"}],
            "references": [{"path": "src/usage.py", "line": 2, "backend": "lsp"}],
            "callers": [{"path": "src/usage.py", "line": 2, "backend": "manual"}],
            "reference_count": 1,
            "caller_count": 1,
            "impacted_files": [{"path": "src/usage.py", "match_count": 1}],
            "related_symbols": [],
            "risk": "low",
            "suggested_review_files": ["src/usage.py"],
        }

    monkeypatch.setattr("app.services.code_intelligence.queries.build_impact_analysis", fake_build_impact_analysis)
    tool = CodeImpactAnalysisTool()
    context = ToolContext(
        user_id="test-user",
        project_ids=[],
        roles=["developer"],
        session_id="session-1",
        project_config={},
        workspace_root=str(tmp_path),
        db=None,
    )

    result = await tool.execute({"symbol": "helper"}, context)

    assert result["provenance"]["definition_backends"] == ["lsp"]
    assert result["provenance"]["reference_backends"] == ["lsp"]
    assert result["provenance"]["caller_backends"] == ["manual"]


def test_summary_domain_coverage_allows_db_override_mapping():
    covered = summary_domains_satisfied_by_result(
        "custom_confluence_digest",
        {"status": "ok"},
        {
            "summary_tool_domains": {"custom_confluence_digest": ["confluence"]},
            "summary_domain_satisfying_tools": {"confluence": ["custom_confluence_digest"]},
        },
    )

    assert covered == {"confluence"}

    names = {item["function"]["name"] for item in get_all_tools_with_plugins("diagnosis")}

    assert "list_mcp_servers" in names
    assert "list_mcp_server_tools" in names
    assert "call_mcp_server_tool" in names
    assert all(not name.startswith("mcp__context7__") for name in names)


def test_turn_diff_tracker_records_commands_files_and_policy_events():
    tracker = TurnDiffTracker()

    tracker.record_tool_call(
        "bash",
        {"command": "git status"},
        {"command": "git status", "returncode": 0, "stdout": "clean", "stderr": ""},
    )
    tracker.record_tool_call(
        "write_workspace_file",
        {"path": "README.md"},
        {"path": "/tmp/README.md", "bytes_written": 42},
    )
    tracker.record_tool_call(
        "apply_patch_workspace",
        {"patch": "***"},
        {"files": [{"path": "/tmp/app.py", "action": "updated"}, {"path": "/tmp/old.txt", "action": "deleted"}]},
    )
    tracker.record_tool_call(
        "bash",
        {"command": "python3 manage.py migrate"},
        {
            "error": "Execution blocked by policy: Diagnosis mode requires approval",
            "command": "python3 manage.py migrate",
            "exec_policy_action": "review",
            "exec_policy_reason": "Diagnosis mode requires approval",
            "exec_policy_risk": "medium",
            "approval_required": True,
        },
    )

    payload = tracker.to_dict()

    assert payload["command_count"] == 2
    assert payload["file_change_count"] == 3
    assert payload["policy_event_count"] == 1
    assert payload["commands"][0]["command"] == "git status"
    assert payload["file_changes"][0]["path"] == "/tmp/README.md"
    assert payload["policy_events"][0]["action"] == "review"


def test_build_system_prompt_mentions_parallel_subthread_consolidation():
    mode = type(
        "Mode",
        (),
        {
            "capability_type": "diagnosis",
            "name": "Diagnosis",
            "key": "diagnosis",
            "prompt_instructions": "",
        },
    )()

    prompt = build_system_prompt(
        agent_type="diagnosis",
        agent_mode=mode,
        personality="",
        memory="",
        skills="",
    )

    assert "spawn_sub_agent" in prompt
    assert "get_context_from_subthreads" in prompt
