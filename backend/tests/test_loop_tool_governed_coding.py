"""Governed coding loop budgets: expected path readiness, fresh reads after failed edits and delivery step forcing."""

from app.agent.loops.outcome._loop_post_tool_coding_delivery import (
    _forced_read_after_failed_governed_coding_edit,
    _governed_coding_evidence_budget_exceeded,
    _governed_coding_expected_paths_ready,
)
from app.agent.loops.outcome._loop_post_tool_delivery_progress import _forced_governed_coding_delivery_progress

# The explicit governed signal: a workflow contract with the approved verification contract (the prompt text is
# never consulted).
GOVERNED = {"workflow_id": "coding_change_tdd", "verification_contract": {"commands": ["pytest"]}}


def test_governed_coding_evidence_budget_uses_progress_quality_event():
    event = _governed_coding_evidence_budget_exceeded(
        workflow_contract=GOVERNED,
        history=[
            {"tool_name": "read_workspace_file", "result": {"path": "a.tf"}},
            {"tool_name": "grep_workspace", "result": {"matches": []}},
        ],
        limit=2,
    )

    assert event is not None
    assert event["evidence_tool_calls"] == 2
    assert event["progress_quality_event"]["kind"] == "tool_activity_stall"


def test_governed_coding_expected_paths_ready_after_all_approved_paths_are_read():
    contract = {**GOVERNED, "expected_paths": ["terraform/base/removed.txt", "terraform/base/irsa.tf"]}

    ready = _governed_coding_expected_paths_ready(
        workflow_contract=contract,
        history=[
            {
                "tool_name": "read_workspace_file",
                "result": {"relative_path": "repo/terraform/base/removed.txt"},
            },
            {
                "tool_name": "read_workspace_file",
                "result": {"relative_path": "repo/terraform/base/irsa.tf"},
            },
        ],
    )

    assert ready is not None
    assert ready["expected_paths"] == ["terraform/base/removed.txt", "terraform/base/irsa.tf"]


def test_governed_coding_expected_paths_ready_stops_after_delivery_tool():
    contract = {**GOVERNED, "expected_paths": ["terraform/base/removed.txt"]}

    assert (
        _governed_coding_expected_paths_ready(
            workflow_contract=contract,
            history=[
                {
                    "tool_name": "read_workspace_file",
                    "result": {"relative_path": "repo/terraform/base/removed.txt"},
                },
                {
                    "tool_name": "apply_patch_workspace",
                    "result": {"changed_files": ["terraform/base/removed.txt"]},
                },
            ],
        )
        is None
    )


def test_failed_governed_coding_edit_forces_fresh_target_read():
    forced = _forced_read_after_failed_governed_coding_edit(
        workflow_contract=GOVERNED,
        history=[
            {
                "tool_name": "edit_workspace_file",
                "parameters": {"path": "terraform/base/memorydb-disable.txt"},
                "result": {"error": "old_string not found in file"},
            }
        ],
    )

    assert forced is not None
    assert forced[0]["function"]["name"] == "read_workspace_file"
    assert '"max_chars": 24000' in forced[0]["function"]["arguments"]
    assert "terraform/base/memorydb-disable.txt" in forced[0]["function"]["arguments"]


def test_governed_coding_delivery_progress_forces_git_diff_check_after_edit():
    user_message = """
    You are Octryx's governed coding agent.
    Execute this approved Work Plan.
    Work Item: ACME-615
    Title: Cleaning Terraform and Helm Config
    """

    forced = _forced_governed_coding_delivery_progress(
        current_user_message=user_message,
        workflow_contract=GOVERNED,
        history=[
            {
                "tool_name": "prepare_bitbucket_repository",
                "result": {
                    "local_path": "/workspace/repo",
                    "project_key": "SHOP",
                    "repo_slug": "aws-shop-infrastructure",
                    "branch_name": "feature/ACME-615-clean-base-terraform-leftovers",
                },
            },
            {"tool_name": "edit_workspace_file", "result": {"status": "edited", "path": "/workspace/repo/main.tf"}},
        ],
    )

    assert forced is not None
    assert forced[0]["function"]["name"] == "run_cli_command"
    assert '"command": "git diff --check"' in forced[0]["function"]["arguments"]
    assert '"cwd": "/workspace/repo"' in forced[0]["function"]["arguments"]


def test_governed_coding_delivery_progress_forces_commit_after_diff():
    user_message = """
    You are Octryx's governed coding agent.
    Execute this approved Work Plan.
    Work Item: ACME-615
    Title: Cleaning Terraform and Helm Config
    """
    history = [
        {
            "tool_name": "prepare_bitbucket_repository",
            "result": {
                "local_path": "/workspace/repo",
                "project_key": "SHOP",
                "repo_slug": "aws-shop-infrastructure",
                "branch_name": "feature/ACME-615-clean-base-terraform-leftovers",
            },
        },
        {"tool_name": "edit_workspace_file", "result": {"status": "edited", "path": "/workspace/repo/main.tf"}},
        {
            "tool_name": "run_cli_command",
            "parameters": {"command": "git diff --check", "cwd": "/workspace/repo"},
            "result": {"exit_code": 0},
        },
        {"tool_name": "get_git_diff", "result": {"cwd": "/workspace/repo", "diff": "diff --git a/main.tf b/main.tf"}},
    ]

    forced = _forced_governed_coding_delivery_progress(
        current_user_message=user_message, history=history, workflow_contract=GOVERNED)

    assert forced is not None
    assert forced[0]["function"]["name"] == "commit_and_push_repository_branch"
    assert "ACME-615: Cleaning Terraform and Helm Config" in forced[0]["function"]["arguments"]


def test_governed_coding_delivery_progress_forces_pr_after_push():
    user_message = """
    You are Octryx's governed coding agent.
    Execute this approved Work Plan.
    Work Item: ACME-615
    Title: Cleaning Terraform and Helm Config
    Source URL: https://jira.example/browse/ACME-615
    """
    history = [
        {
            "tool_name": "prepare_bitbucket_repository",
            "result": {
                "local_path": "/workspace/repo",
                "project_key": "SHOP",
                "repo_slug": "aws-shop-infrastructure",
                "branch_name": "feature/ACME-615-clean-base-terraform-leftovers",
            },
        },
        {"tool_name": "edit_workspace_file", "result": {"status": "edited", "path": "/workspace/repo/main.tf"}},
        {
            "tool_name": "run_cli_command",
            "parameters": {"command": "git diff --check", "cwd": "/workspace/repo"},
            "result": {"exit_code": 0},
        },
        {"tool_name": "get_git_diff", "result": {"cwd": "/workspace/repo", "diff": "diff --git a/main.tf b/main.tf"}},
        {
            "tool_name": "commit_and_push_repository_branch",
            "result": {
                "status": "pushed",
                "branch_name": "feature/ACME-615-clean-base-terraform-leftovers",
                "head_commit": "abc123",
            },
        },
    ]

    forced = _forced_governed_coding_delivery_progress(
        current_user_message=user_message, history=history, workflow_contract=GOVERNED)

    assert forced is not None
    assert forced[0]["function"]["name"] == "create_bitbucket_pull_request"
    assert "https://jira.example/browse/ACME-615" in forced[0]["function"]["arguments"]


def test_a_governed_sounding_prompt_without_the_contract_is_not_governed():
    """The prompt wording never decides: only the workflow contract's verification contract does."""
    from app.agent.loops.control._loop_progress_quality import detect_unsupported_no_tool_progress_claim

    history = [{"tool_name": "edit_workspace_file", "parameters": {"path": "main.tf"},
                "result": {"error": "old_string not found in file"}}]
    for contract in (None, {}, {"workflow_id": "coding_change_tdd"}, {"expected_paths": ["main.tf"]}):
        assert _forced_read_after_failed_governed_coding_edit(history=history, workflow_contract=contract) is None
        assert _governed_coding_expected_paths_ready(history=history, workflow_contract=contract) is None
        assert _governed_coding_evidence_budget_exceeded(history=history, limit=1, workflow_contract=contract) is None
    assert detect_unsupported_no_tool_progress_claim(assistant_content="I updated the files.", history=[],
                                                     is_governed=False) is None
