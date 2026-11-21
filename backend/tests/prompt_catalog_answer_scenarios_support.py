"""Fixed inputs of the answer-text scenarios, rendered through the current code.

``tests/prompt_catalog_golden_keys_answer.py`` pins ``SCENARIOS``: the SHA-256 of the rendered output for
exactly these inputs.
"""

from __future__ import annotations

from hashlib import sha256
from types import SimpleNamespace

CODING_RESULTS = [
    {"tool_name": "run_test_suite", "result": {"all_green": True, "command": ["mvn", "test"], "passed": 4}},
    {"tool_name": "run_cli_command", "result": {"exit_code": 0, "command": "mvn -q clean verify"}},
]
CODING_HISTORY = [
    {"tool_name": "edit_workspace_file", "result": {"relative_path": "src/App.java"}},
    {"tool_name": "write_workspace_file", "result": {"path": "README.md"}},
]
CHILD_HISTORY = [
    {"tool_name": "read_workspace_file", "result": {"path": "pom.xml"}},
    {"tool_name": "grep_workspace", "result": {"matches": [{"file": "src/A.java"}]}},
    {"tool_name": "bash", "result": {"error": "denied"}},
]
DIAGRAM_CALLS = [SimpleNamespace(tool_name="create_diagram", result={"diagram_id": "d-1", "title": "Topology"})]
JIRA_BUNDLE = {
    "project_key": "RIVER",
    "release_name": "2.4.20",
    "release_date": "2026-10-10",
    "version_id": "77",
    "sprint_name": "S42",
    "sprint_id": "9",
    "board_id": "3",
    "assigned_to_sprint": ["RIVER-1", "RIVER-2"],
    "created_tickets": [
        {"ticket_id": "RIVER-1", "summary": "Do", "priority": "High", "issue_type": "Task", "assignee": "alice",
         "references": ["https://x/1"]},
        {"ticket_id": "RIVER-2"},
    ],
    "updated_tickets": [{"ticket_id": "RIVER-3"}],
}
PR_MESSAGE = "Work Item: RIVER-615\nTitle: Upgrade Spring Boot\nSource URL: https://jira/RIVER-615"


def answer_outputs() -> dict[str, str]:
    from app.agent.loops.control._loop_coding_completion import build_direct_coding_completion_message
    from app.agent.loops.outcome import _loop_post_tool_delivery_progress as delivery
    from app.agent.loops.outcome._loop_post_tool_history import _read_only_child_wrapup_content
    from app.agent.loops.response import _loop_message_response_policy as policy
    from app.agent.loops.response._loop_jira_bundle_report import _build_jira_sprint_bundle_report
    from app.agent.loops.response._loop_runtime_salvage import _build_diagram_artifact_salvage_message
    from app.agent.loops.runtime._loop_runtime_turn_failure import _runtime_unreachable_user_message

    return {
        "salvage:presentation": policy.build_runtime_salvage_presentation_message(topic="Shipping", relative_path="d.pptx"),
        "salvage:presentation:nofile": policy.build_runtime_salvage_presentation_message(topic="Shipping", relative_path=""),
        "salvage:outline": policy.build_runtime_salvage_outline_from_evidence_message(),
        "salvage:weekly": policy.build_runtime_salvage_weekly_summary_message(
            jira_count=3, bitbucket_count=2, confluence_count=1
        ),
        "salvage:office": policy.build_runtime_salvage_office_artifact_message(relative_path="r.docx"),
        "status:empty": policy.build_tool_execution_status_message(tool_names=[]),
        "status:one": policy.build_tool_execution_status_message(tool_names=["jira_search"]),
        "status:many": policy.build_tool_execution_status_message(tool_names=["a", "b", "c", "d"]),
        "runtime:unreachable": str(
            _runtime_unreachable_user_message([{"status": "error", "error_class": "timeout"}])
        ),
        "coding:completed": str(
            build_direct_coding_completion_message(tool_results=CODING_RESULTS, turn_tool_history=CODING_HISTORY)
        ),
        "diagram:salvage": _build_diagram_artifact_salvage_message(DIAGRAM_CALLS),
        "child:wrapup": _read_only_child_wrapup_content(current_user_message=" Inspect pom ", history=CHILD_HISTORY),
        "child:wrapup:empty": _read_only_child_wrapup_content(current_user_message="", history=[]),
        "jira:bundle": _build_jira_sprint_bundle_report(JIRA_BUNDLE),
        "jira:bundle:bare": _build_jira_sprint_bundle_report({}),
        "delivery:commit": delivery._governed_coding_commit_message(PR_MESSAGE),
        "delivery:commit:default": delivery._governed_coding_commit_message("no work item"),
        "delivery:pr": delivery._governed_coding_pr_description(PR_MESSAGE, {"head_commit": "abc123"}),
        "delivery:pr:nosource": delivery._governed_coding_pr_description("x", {"head_commit": "abc"}),
    }


def answer_digests() -> dict[str, str]:
    return {name: sha256(text.encode("utf-8")).hexdigest() for name, text in answer_outputs().items()}
