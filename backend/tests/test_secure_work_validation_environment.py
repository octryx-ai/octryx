from app.services.coding_validation import build_validation_outcome
from app.services.workspace_change_safety import is_validation_command


def test_validation_outcome_marks_passing_command():
    outcome = build_validation_outcome(command="terraform validate", cwd="/repo", exit_code=0)

    assert outcome["status"] == "passed"
    assert outcome["blocker"] == ""
    assert outcome["executable"] == "terraform"


def test_validation_outcome_marks_failing_command():
    outcome = build_validation_outcome(
        command="pytest -q",
        cwd="/repo",
        exit_code=1,
        stdout="failed",
    )

    assert outcome["status"] == "failed"
    assert outcome["blocker"] == "validation_failed"


def test_validation_outcome_marks_missing_tool():
    outcome = build_validation_outcome(
        command="terraform validate",
        cwd="/repo",
        exit_code=127,
        stderr="terraform: command not found",
    )

    assert outcome["status"] == "missing_tool"
    assert outcome["blocker"] == "validation_tool_missing"
    assert "`terraform`" in outcome["required_action"]


def test_validation_outcome_marks_wrong_cwd():
    outcome = build_validation_outcome(
        command="terraform validate",
        cwd="../outside",
        error="cwd must stay inside workspace root",
    )

    assert outcome["status"] == "wrong_cwd"
    assert outcome["blocker"] == "validation_cwd_invalid"


def test_terraform_validate_is_a_validation_command():
    assert is_validation_command(["terraform", "validate"]) is True
    assert is_validation_command(["terraform", "fmt", "-check"]) is True
