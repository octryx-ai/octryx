from app.services.stuck_loop_detector import (
    build_iteration_ceiling_event,
    detect_no_tool_stuck_loop,
    detect_tool_stuck_loop,
    get_stuck_loop_detector_settings,
)


def test_detect_tool_stuck_loop_repetitive_tool():
    step = {"name": "Investigate", "stepType": "analysis"}
    history = [
        {"tool_name": "search_jira_tickets", "result": {}},
        {"tool_name": "search_jira_tickets", "result": {}},
        {"tool_name": "search_jira_tickets", "result": {}},
        {"tool_name": "search_jira_tickets", "result": {}},
        {"tool_name": "search_jira_tickets", "result": {}},
    ]

    event = detect_tool_stuck_loop(
        step=step,
        history=history,
        step_index=1,
        runtime_settings={"stuck_loop_tool_repeat_threshold": 5},
    )

    assert event is not None
    assert event["kind"] == "repetitive_tool_loop"
    assert event["signal_count"] == 5
    assert event["details"]["tool_name"] == "search_jira_tickets"


def test_detect_tool_stuck_loop_repetitive_tool_errors():
    step = {"name": "Gather sources", "stepType": "analysis"}
    history = [
        {"tool_name": "web_search", "result": {"error": "DuckDuckGo search failed"}},
        {"tool_name": "web_search", "result": {"error": "DuckDuckGo search failed"}},
    ]

    event = detect_tool_stuck_loop(
        step=step,
        history=history,
        step_index=0,
        runtime_settings={"stuck_loop_blocked_tool_threshold": 2},
    )

    assert event is not None
    assert event["kind"] == "repetitive_tool_error_loop"
    assert event["signal_count"] == 2
    assert event["details"]["tool_name"] == "web_search"


def test_detect_tool_stuck_loop_repetitive_empty_search_results():
    step = {"name": "Gather sources", "stepType": "analysis"}
    history = [
        {"tool_name": "web_search", "result": {"count": 0, "items": []}},
        {"tool_name": "web_search", "result": {"count": 0, "items": []}},
    ]

    event = detect_tool_stuck_loop(
        step=step,
        history=history,
        step_index=0,
        runtime_settings={"stuck_loop_empty_search_threshold": 2},
    )

    assert event is not None
    assert event["kind"] == "repetitive_empty_search_loop"
    assert event["signal_count"] == 2
    assert event["details"]["tool_name"] == "web_search"


def test_detect_tool_stuck_loop_repeated_same_target_without_step():
    history = [
        {"tool_name": "get_confluence_page", "params": {"page_id": "100104"}, "result": {}},
        {"tool_name": "get_confluence_page", "params": {"page_id": "100105"}, "result": {}},
        {"tool_name": "get_confluence_page", "params": {"page_id": "100104"}, "result": {}},
        {"tool_name": "get_confluence_page", "params": {"page_id": "100107"}, "result": {}},
        {"tool_name": "get_confluence_page", "params": {"page_id": "100104"}, "result": {}},
    ]

    event = detect_tool_stuck_loop(
        step=None,
        history=history,
        step_index=0,
        runtime_settings={"stuck_loop_same_target_threshold": 3},
    )

    assert event is not None
    assert event["kind"] == "repeated_same_target_loop"
    assert event["details"]["tool_name"] == "get_confluence_page"
    assert event["details"]["target"] == "100104"
    assert event["signal_count"] == 3


def test_detect_tool_stuck_loop_repetitive_meta_tool():
    history = [
        {"tool_name": "load_tool_artifact", "params": {"artifact_id": "a1"}, "result": {}},
        {"tool_name": "load_tool_artifact", "params": {"artifact_id": "a2"}, "result": {}},
        {"tool_name": "load_tool_artifact", "params": {"artifact_id": "a3"}, "result": {}},
        {"tool_name": "load_tool_artifact", "params": {"artifact_id": "a4"}, "result": {}},
    ]

    event = detect_tool_stuck_loop(
        step=None,
        history=history,
        step_index=0,
        runtime_settings={"stuck_loop_tool_repeat_threshold": 5},
    )

    assert event is not None
    assert event["kind"] == "repetitive_meta_tool_loop"
    assert event["details"]["tool_name"] == "load_tool_artifact"
    assert event["signal_count"] == 3


def test_detect_tool_stuck_loop_repetitive_knowledge_lookup_cycle():
    history = [
        {"tool_name": "knowledge_search", "params": {"query": "latest release"}, "result": {"count": 10}},
        {
            "tool_name": "knowledge_read",
            "params": {"evidence_key": "jira-release-acme-45034"},
            "result": {"error": "Knowledge evidence not found or not readable from this Workspace"},
        },
        {"tool_name": "search_confluence", "params": {"query": "latest release"}, "result": {"count": 15}},
        {"tool_name": "knowledge_search", "params": {"query": "latest release"}, "result": {"count": 10}},
        {
            "tool_name": "knowledge_read",
            "params": {"evidence_key": "jira-release-acme-45034"},
            "result": {"error": "Knowledge evidence not found or not readable from this Workspace"},
        },
        {"tool_name": "search_confluence", "params": {"query": "latest release"}, "result": {"count": 15}},
    ]

    event = detect_tool_stuck_loop(
        step=None,
        history=history,
        step_index=0,
        runtime_settings={"stuck_loop_same_target_threshold": 3},
    )

    assert event is not None
    assert event["kind"] == "repetitive_knowledge_lookup_loop"
    assert "knowledge_read" in event["details"]["tools"]


def test_detect_tool_stuck_loop_repetitive_repository_evidence_cycle():
    history = [
        {"tool_name": "prepare_bitbucket_repository", "params": {"repo_slug": "demo-infra"}, "result": {}},
        {"tool_name": "list_workspace_directory", "params": {"path": "terraform/base"}, "result": {}},
        {"tool_name": "read_workspace_file", "params": {"path": "terraform/base/removed.txt"}, "result": {}},
        {"tool_name": "read_workspace_file", "params": {"path": "terraform/base/irsa.tf"}, "result": {}},
        {"tool_name": "bash", "params": {"command": "git status"}, "result": {"stdout": "clean"}},
        {"tool_name": "prepare_bitbucket_repository", "params": {"repo_slug": "demo-infra"}, "result": {}},
        {"tool_name": "list_workspace_directory", "params": {"path": "terraform/base"}, "result": {}},
        {"tool_name": "read_workspace_file", "params": {"path": "terraform/base/removed.txt"}, "result": {}},
    ]

    event = detect_tool_stuck_loop(
        step=None,
        history=history,
        step_index=0,
        runtime_settings={"stuck_loop_same_target_threshold": 3},
    )

    assert event is not None
    assert event["kind"] == "repetitive_evidence_target_cycle"
    assert "read_workspace_file" in event["details"]["tools"]
    assert "terraform/base/removed.txt" in event["details"]["targets"]


def test_detect_no_tool_stuck_loop_duplicate_response():
    event = detect_no_tool_stuck_loop(
        step={"name": "Summarize"},
        step_index=2,
        current_content="I already summarized that step.",
        current_signature="summary-repeat",
        previous_content="I already summarized that step.",
        previous_signature="summary-repeat",
        similarity=0.93,
        duplicate_count=2,
        repeated_previous_step_summary_count=0,
        repeated_previous_step_summary=False,
        runtime_settings={
            "stuck_loop_no_tool_duplicate_threshold": 2,
            "stuck_loop_no_tool_similarity_threshold": 0.8,
        },
    )

    assert event is not None
    assert event["kind"] == "duplicate_no_tool_response"
    assert event["recommended_action"] == "stop_or_recover"


def test_build_iteration_ceiling_event_reports_attempts():
    event = build_iteration_ceiling_event(
        step={"name": "Collect evidence"},
        step_index=0,
        attempts_used=8,
        max_iterations=8,
    )

    assert event["kind"] == "iteration_ceiling"
    assert event["severity"] == "error"
    assert event["details"]["attempts_used"] == 8
    assert event["details"]["max_iterations"] == 8


def test_stuck_loop_detector_settings_are_bounded():
    settings = get_stuck_loop_detector_settings(
        {
            "stuck_loop_tool_repeat_threshold": 99,
            "stuck_loop_blocked_tool_threshold": -1,
            "stuck_loop_empty_search_threshold": 99,
            "stuck_loop_no_tool_similarity_threshold": 1.5,
        }
    )

    assert settings["tool_repeat_threshold"] == 12
    assert settings["blocked_tool_threshold"] == 1
    assert settings["empty_search_threshold"] == 6
    assert settings["no_tool_similarity_threshold"] == 0.99
