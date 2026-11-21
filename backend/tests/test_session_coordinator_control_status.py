"""The session coordinator status endpoint rolls up the document flow summary of a root session and its children."""

import uuid

import pytest
from sqlalchemy import select

from app.models import Session, SubAgentGroup, ToolCall, User
from app.time_utils import utc_now


def _document_flow_tool_calls(root_session_id: str, child_session_id: str) -> list[ToolCall]:
    return [
        ToolCall(
            id=str(uuid.uuid4()),
            session_id=child_session_id,
            tool_name="ingest_document_source",
            parameters={"source": "https://example.com/ticketing-api"},
            result={"relative_path": "research_bundles/ticketing/source-a.parsed.txt"},
            status="success",
        ),
        ToolCall(
            id=str(uuid.uuid4()),
            session_id=root_session_id,
            tool_name="get_context_from_subthreads",
            parameters={},
            result={
                "accepted_count": 1,
                "rejected_count": 2,
                "accepted_subthreads": [{"session_id": child_session_id}],
                "rejected_subthreads": [{"session_id": "child-bad-a"}, {"session_id": "child-bad-b"}],
            },
            status="success",
        ),
        ToolCall(
            id=str(uuid.uuid4()),
            session_id=root_session_id,
            tool_name="write_workspace_file",
            parameters={"path": "ticketing_report_plan.json"},
            result={"path": "ticketing_report_plan.json"},
            status="success",
        ),
        ToolCall(
            id=str(uuid.uuid4()),
            session_id=root_session_id,
            tool_name="build_word_template_script",
            parameters={"file_path": "ticketing_report.docx"},
            result={"relative_path": "ticketing_report.docx"},
            status="success",
        ),
        ToolCall(
            id=str(uuid.uuid4()),
            session_id=root_session_id,
            tool_name="validate_office_document",
            parameters={"path": "ticketing_report.docx"},
            result={"valid": True, "path": "ticketing_report.docx"},
            status="success",
        ),
    ]


@pytest.mark.asyncio
async def test_get_session_coordinator_status_rolls_up_document_flow_summary(client, auth_headers, db):
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    root_session = Session(
        id=str(uuid.uuid4()),
        user_id=admin.id,
        status="awaiting_subagents",
        metadata_={"title": "Coordinator Document Root", "routing_intent": "documentation"},
    )
    child_session = Session(
        id=str(uuid.uuid4()),
        user_id=admin.id,
        status="completed",
        parent_session_id=root_session.id,
        sub_agent_depth=1,
        metadata_={"title": "Research child"},
    )
    group = SubAgentGroup(
        id=str(uuid.uuid4()),
        parent_session_id=root_session.id,
        status="running",
        total_count=1,
        completed_count=1,
        failed_count=0,
        child_session_ids_json=[child_session.id],
        child_statuses_json={child_session.id: "completed"},
        created_at=utc_now(),
    )
    root_session.metadata_["current_sub_agent_group_id"] = group.id
    db.add_all(
        [
            root_session,
            child_session,
            group,
            *_document_flow_tool_calls(root_session.id, child_session.id),
        ]
    )
    await db.commit()

    response = await client.get(
        f"/api/v1/sessions/{root_session.id}/coordinator-status",
        headers=auth_headers,
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["coordinator_mode"] == "sub_agent_group"
    assert payload["progress_counts"]["total_children"] == 1
    assert payload["progress_counts"]["completed_children"] == 1
    assert payload["document_flow"] == {
        "flow_type": "research_document",
        "source_bundle_count": 1,
        "accepted_subthread_count": 1,
        "rejected_subthread_count": 2,
        "plan_written": True,
        "document_built": True,
        "document_validated": True,
        "artifact_path": "ticketing_report.docx",
    }
