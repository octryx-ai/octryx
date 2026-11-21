from datetime import timedelta

from app.models import SubAgentGroup
from app.services.sub_agent_group.telemetry import summarize_sub_agent_group_telemetry
from app.time_utils import utc_now


def test_summarize_sub_agent_group_telemetry_reports_progress_and_readiness():
    now = utc_now()
    group = SubAgentGroup(
        id="group-progress",
        parent_session_id="parent-1",
        status="running",
        total_count=3,
        completed_count=1,
        failed_count=1,
        child_session_ids_json=["child-a", "child-b", "child-c"],
        child_statuses_json={"child-a": "completed", "child-b": "failed"},
        created_at=now - timedelta(minutes=6),
        updated_at=now - timedelta(minutes=1),
        timeout_at=now + timedelta(minutes=4),
    )

    payload = summarize_sub_agent_group_telemetry(group, now=now)

    assert payload["coordinator_type"] == "sub_agent_group"
    assert payload["terminal_state"] == "in_progress"
    assert payload["progress"] == {
        "total_children": 3,
        "completed_children": 1,
        "failed_children": 1,
        "timed_out_children": 0,
        "terminal_children": 2,
        "pending_children": 1,
        "completion_ratio": 0.6667,
    }
    assert payload["readiness"] == {
        "all_children_terminal": False,
        "parent_resume_ready": False,
        "parent_resume_started": False,
        "group_is_terminal": False,
        "counts_match_state": True,
    }
    assert payload["timing"]["elapsed_seconds"] == 360
    assert payload["timing"]["timeout_remaining_seconds"] == 240
    assert payload["child_status_counts"] == {"completed": 1, "failed": 1, "timed_out": 0}


def test_summarize_sub_agent_group_telemetry_surfaces_terminal_failures_and_count_drift():
    now = utc_now()
    group = SubAgentGroup(
        id="group-terminal",
        parent_session_id="parent-2",
        status="completed",
        total_count=2,
        completed_count=2,
        failed_count=0,
        child_session_ids_json=["child-a", "child-b"],
        child_statuses_json={"child-a": "completed", "child-b": "timed_out"},
        created_at=now - timedelta(minutes=10),
        updated_at=now - timedelta(minutes=2),
        completed_at=now - timedelta(minutes=3),
        resumed_at=now - timedelta(minutes=2),
        timeout_at=now - timedelta(minutes=1),
        last_error="timeout in child-b",
    )

    payload = summarize_sub_agent_group_telemetry(group, now=now)

    assert payload["terminal_state"] == "completed_with_failures"
    assert payload["progress"]["failed_children"] == 1
    assert payload["progress"]["timed_out_children"] == 1
    assert payload["progress"]["pending_children"] == 0
    assert payload["progress"]["completion_ratio"] == 1.0
    assert payload["readiness"]["all_children_terminal"] is True
    assert payload["readiness"]["parent_resume_ready"] is True
    assert payload["readiness"]["parent_resume_started"] is True
    assert payload["readiness"]["group_is_terminal"] is True
    assert payload["readiness"]["counts_match_state"] is False
    assert payload["timing"]["elapsed_seconds"] == 420
    assert payload["timing"]["timeout_remaining_seconds"] == 0
    assert payload["last_error"] == "timeout in child-b"
