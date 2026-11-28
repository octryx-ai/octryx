from datetime import UTC, datetime
from types import SimpleNamespace

from app.web._helpers._chat_selected_session_contract import build_selected_chat_session_contract


def test_selected_chat_session_contract_preserves_legacy_fields():
    selected_session = SimpleNamespace(
        id="session-1",
        project_id="project-1",
        agent_type="coding",
        started_at=datetime(2026, 4, 20, 10, 30, tzinfo=UTC),
        metadata_={
            "agent_selection_source": "default",
            "resume_state": "resume_pending",
            "title": "Session title from metadata",
            "pinned": True,
        },
    )
    user = SimpleNamespace(id="user-1")

    payload = build_selected_chat_session_contract(
        selected_session=selected_session,
        selected_row=None,
        selected_project=SimpleNamespace(name="Project One"),
        selected_status="active",
        selected_run_status="completed",
        selected_run_completion_reason="completed",
        selected_runtime_target_id="runtime-1",
        selected_runtime_label="Runtime One",
        selected_agent_id="agent-1",
        selected_agent_name="Agent One",
        selected_stop_reason="user_cancelled",
        selected_task_run_id="task-run-1",
        selected_task_status="success",
        selected_task_error="",
        selected_approvals=[{"status": "pending"}, {"status": "approved"}],
        user=user,
    )

    assert payload == {
        "id": "session-1",
        "threadNumber": 0,
        "title": "Session title from metadata",
        "titleSource": None,
        "status": "active",
        "runStatus": "completed",
        "runCompletionReason": "completed",
        "projectId": "project-1",
        "projectName": "Project One",
        "isPinned": True,
        "runtimeTargetId": "runtime-1",
        "runtimeLabel": "Runtime One",
        "agentId": "agent-1",
        "agentName": "Agent One",
        "agentType": "coding",
        "agentSelectionSource": "default",
        "workflowKey": "",
        "routingIntent": None,
        "routingReason": None,
        "resumeState": "resume_pending",
        "writePlan": None,
        # The contract carries the turn's workflow proposal; none was made here.
        "workflowProposal": None,
        "canGrantStandingConfirmation": False,
        "stopReason": "user_cancelled",
        "startedAt": "2026-04-20T10:30:00Z",
        "taskRunId": "task-run-1",
        "taskStatus": "success",
        "taskError": "",
        "approvalCount": 2,
        "pendingApprovalCount": 1,
        "streamToken": payload["streamToken"],
    }
    assert isinstance(payload["streamToken"], str)
    assert payload["streamToken"]


def test_selected_chat_session_contract_prefers_thread_row_over_fallbacks():
    selected_session = SimpleNamespace(
        id="session-2",
        project_id="project-2",
        agent_type="diagnosis",
        started_at=datetime(2026, 4, 20, 11, 0, tzinfo=UTC),
        metadata_={},
    )
    user = SimpleNamespace(id="user-2")

    payload = build_selected_chat_session_contract(
        selected_session=selected_session,
        selected_row={
            "thread_number": 7,
            "title": "Thread row title",
            "project_name": "Thread Project",
            "is_pinned": False,
        },
        selected_project=None,
        selected_status="running",
        selected_run_status="in_progress",
        selected_run_completion_reason="",
        selected_runtime_target_id="",
        selected_runtime_label="Auto",
        selected_agent_id="",
        selected_agent_name="",
        selected_stop_reason=None,
        selected_task_run_id="",
        selected_task_status="",
        selected_task_error="failure",
        selected_approvals=[],
        user=user,
    )

    assert payload["threadNumber"] == 7
    assert payload["title"] == "Thread row title"
    assert payload["projectName"] == "Thread Project"
    assert payload["isPinned"] is False


def test_selected_chat_session_contract_workflow_key():
    def _payload(metadata: dict) -> dict:
        return build_selected_chat_session_contract(
            selected_session=SimpleNamespace(
                id="session-3",
                project_id=None,
                agent_type="diagnosis",
                started_at=datetime(2026, 7, 18, 9, 0, tzinfo=UTC),
                metadata_=metadata,
            ),
            selected_row=None,
            selected_project=None,
            selected_status="active",
            selected_run_status="completed",
            selected_run_completion_reason="completed",
            selected_runtime_target_id="",
            selected_runtime_label="Auto",
            selected_agent_id="",
            selected_agent_name="",
            selected_stop_reason=None,
            selected_task_run_id="",
            selected_task_status="",
            selected_task_error="",
            selected_approvals=[],
            user=SimpleNamespace(id="user-3"),
        )

    assert _payload({})["workflowKey"] == "", "a thread without a turn yet runs the standard"
    assert _payload({"workflow_key": ""})["workflowKey"] == ""
    assert _payload({"workflow_key": "aws-topology-diagram-routing"})["workflowKey"] == (
        "aws-topology-diagram-routing"
    )
