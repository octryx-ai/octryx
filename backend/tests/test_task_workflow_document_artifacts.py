"""The code artifact contract: a workspace mutation and a green test run complete it."""

from app.services.workflow_contracts.artifact_contract import workflow_artifact_contract_satisfied


def test_workflow_code_artifact_contract_requires_mutation_and_green_tests():
    contract = {
        "workflow_id": "coding_change_tdd",
        "artifact_type": "code",
    }
    analyze_only = [
        {
            "tool_name": "analyze_workspace_repository",
            "status": "success",
            "result": {"path": "/tmp/workspace"},
        }
    ]
    mutation_without_tests = analyze_only + [
        {
            "tool_name": "edit_workspace_file",
            "status": "success",
            "result": {"path": "/tmp/workspace/app.py", "relative_path": "app.py"},
        }
    ]
    mutation_with_green_tests = mutation_without_tests + [
        {
            "tool_name": "run_test_suite",
            "status": "success",
            "result": {"all_green": True, "passed": 4, "failed": 0, "errors": 0},
        }
    ]

    assert workflow_artifact_contract_satisfied(contract, turn_tool_history=analyze_only) is False
    assert workflow_artifact_contract_satisfied(contract, turn_tool_history=mutation_without_tests) is False
    assert workflow_artifact_contract_satisfied(contract, turn_tool_history=mutation_with_green_tests) is True
