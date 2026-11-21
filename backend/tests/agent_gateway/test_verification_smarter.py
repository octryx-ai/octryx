"""The "done means verified" gate asks for a test only where one makes sense: a session that writes a test.txt is
not pushed to invent a pytest run. Only code changes count, the common runners count, and a folder without any
test setup gets no forced test."""

from __future__ import annotations

import uuid
from datetime import timedelta

import pytest

from app.models import ToolCall
from app.services.agent_gateway.policy import build_policy
from app.services.agent_gateway.policy_normalize import normalize_agent_gateway_policy
from app.services.agent_gateway.verification import evaluate_verification
from app.time_utils import utc_now

POLICY = build_policy(normalize_agent_gateway_policy({"verification": {
    "test_command_prefixes": [["pytest"]], "change_tools": ["Edit", "Write", "MultiEdit", "NotebookEdit"]}}),
    source="workspace")


def _row(tool: str, seconds: int, *, path: str = "", command: str = "", ok: bool = True) -> ToolCall:
    parameters = {"source": "model_gateway", "tool_use_id": uuid.uuid4().hex, "block_index": 0,
                  "input": {"file_path": path} if path else {}}
    if command:
        parameters["command"] = command
    return ToolCall(session_id="s", tool_name=tool, parameters=parameters, result={"is_error": not ok, "excerpt": ""},
                    status="success" if ok else "error", created_at=utc_now() + timedelta(seconds=seconds))


def test_a_text_or_document_change_needs_no_test():
    rows = [_row("Write", 1, path="/Users/l/Documents/OCX/test.txt"), _row("Edit", 2, path="/repo/README.md"),
            _row("Write", 3, path="/repo/docs/deck.pptx")]
    result = evaluate_verification(POLICY, rows)
    assert (result.state, result.reason) == ("not_applicable", "no_code_change")


def test_a_code_change_still_needs_a_test_and_unknown_paths_count_as_code():
    assert evaluate_verification(POLICY, [_row("Write", 1, path="/repo/app.py")]).reason == "no_test_after_last_change"
    assert evaluate_verification(POLICY, [_row("Edit", 1)]).reason == "no_test_after_last_change"
    rows = [_row("Edit", 1, path="/repo/app.py"), _row("Write", 2, path="/repo/NOTES.md")]
    assert evaluate_verification(POLICY, rows).state == "blocked"  # a later doc change does not hide the code change


@pytest.mark.parametrize("command", ["npm test", "pnpm run test -- --run", "npx vitest run", "mvn test",
                                     "./gradlew test", "go test ./...", "cargo test", "make test", "uv run pytest -q",
                                     "cd web && npm test"])
def test_the_common_test_runners_count(command):
    rows = [_row("Edit", 1, path="/repo/src/main.ts"), _row("Bash", 2, command=command)]
    assert evaluate_verification(POLICY, rows).state == "passed"


def test_no_test_setup_means_no_forced_test_but_a_run_test_still_decides():
    rows = [_row("Write", 1, path="/Users/l/scripts/tool.sh")]
    result = evaluate_verification(POLICY, rows, test_setup=False)
    assert (result.state, result.reason) == ("not_applicable", "no_test_setup")
    assert evaluate_verification(POLICY, rows, test_setup=True).state == "blocked"
    assert evaluate_verification(POLICY, rows, test_setup=None).state == "blocked"
    failed = [*rows, _row("Bash", 2, command="pytest -q", ok=False)]
    assert evaluate_verification(POLICY, failed, test_setup=False).state == "blocked"
