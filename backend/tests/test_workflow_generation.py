import uuid

import pytest
from sqlalchemy import select

from app.models import FlowDefinition, Message, Session, ToolCall, TurnTrace, User
from app.services.workflow_runs.graph_validation import validate_phased_definition


@pytest.mark.asyncio
async def test_generate_workflow_from_session_creates_reviewable_draft(client, auth_headers, db):
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    session = Session(
        id=str(uuid.uuid4()),
        user_id=admin.id,
        agent_type="diagnosis",
        status="completed",
        metadata_={"title": "AWS investigation"},
    )
    user_message = Message(
        id=str(uuid.uuid4()),
        session_id=session.id,
        role="user",
        content="Investigate AWS exposure and produce a concise report.",
    )
    assistant_message = Message(
        id=str(uuid.uuid4()),
        session_id=session.id,
        role="assistant",
        content="Collected topology and exposure evidence.",
    )
    tool_call = ToolCall(
        id=str(uuid.uuid4()),
        session_id=session.id,
        message_id=assistant_message.id,
        tool_name="aws_exposure_map",
        status="success",
        result={"status": "ok"},
    )
    trace = TurnTrace(
        id=str(uuid.uuid4()),
        session_id=session.id,
        message_id=assistant_message.id,
        provider="bedrock",
        model="sonnet",
        context_snapshot_json={"request_analysis": {"requested_domains": ["aws"]}},
        usage_json={"prompt_tokens": 100, "completion_tokens": 20},
    )
    db.add_all([session, user_message, assistant_message, tool_call, trace])
    await db.commit()

    response = await client.post(
        f"/api/v1/flows/generate-from-session/{session.id}",
        headers=auth_headers,
        json={},
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["status"] == "draft_created"
    assert payload["review_summary"]["review_status"] == "needs_human_review"
    assert payload["source_evidence"]["message_ids"] == [user_message.id, assistant_message.id]
    assert payload["source_evidence"]["tool_call_ids"] == [tool_call.id]
    assert payload["source_evidence"]["trace_ids"] == [trace.id]
    flow = payload["flow"]
    assert flow["status"] == "draft"
    version = flow["versions"][0]
    assert version["status"] == "draft"
    definition = version["definition"]
    # D2b: the generator emits the designer's one format, a valid phased workflow.
    assert definition["execution_kind"] == "phased"
    assert version["validation_report"]["valid"] is True
    assert validate_phased_definition(definition)["valid"] is True
    kinds = [node["type"] for node in definition["nodes"]]
    assert kinds == ["start", "phase", "gate", "decision", "approval", "outcome", "outcome", "outcome"]
    phase = next(node for node in definition["nodes"] if node["type"] == "phase")
    assert phase["config"]["tool_policy"]["allowlist"] == ["aws_exposure_map"]
    assert phase["config"]["workflow_contract"]["capability_class"] == "read_only"
    assert phase["config"]["agent"] == "assistant"
    assert phase["config"]["result_values"] == ["complete", "incomplete"]
    assert {edge["when"] for edge in definition["edges"] if edge["source"] == "result"} == {"complete", "otherwise"}
    assert version["policy_bindings"]["safety_class"] == "review_required"

    # It round-trips: saved again as a draft unchanged, it stays the same valid graph.
    saved = await client.post(f"/api/v1/flows/{flow['id']}/drafts", headers=auth_headers, json={
        "expected_latest_version_id": version["id"], "name": flow["name"], "definition": definition})
    assert saved.status_code == 200, saved.text
    again = max(saved.json()["versions"], key=lambda item: item["version"])
    assert again["definition"] == definition and again["validation_report"]["valid"] is True

    rows = (await db.execute(select(FlowDefinition).where(FlowDefinition.id == flow["id"]))).scalars().all()
    assert len(rows) == 1
    assert rows[0].status == "draft"

    archive_response = await client.post(
        f"/api/v1/flows/{flow['id']}/archive",
        headers=auth_headers,
    )
    assert archive_response.status_code == 200, archive_response.text
    archived = archive_response.json()
    assert archived["status"] == "archived"
    assert archived["is_active"] is False
    assert archived["versions"][-1]["status"] == "archived"


@pytest.mark.asyncio
async def test_a_session_without_tool_evidence_generates_a_valid_investigation_placeholder(client, auth_headers, db):
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    session = Session(id=str(uuid.uuid4()), user_id=admin.id, agent_type="diagnosis", status="completed",
                      metadata_={})
    message = Message(id=str(uuid.uuid4()), session_id=session.id, role="user", content="Summarise the outage.")
    failed_call = ToolCall(id=str(uuid.uuid4()), session_id=session.id, tool_name="not_a_known_tool",
                           status="error", result={})
    db.add_all([session, message, failed_call])
    await db.commit()

    response = await client.post(f"/api/v1/flows/generate-from-session/{session.id}", headers=auth_headers,
                                 json={"name": "Outage summary"})

    assert response.status_code == 200, response.text
    version = response.json()["flow"]["versions"][0]
    definition = version["definition"]
    assert validate_phased_definition(definition)["valid"] is True
    phase = next(node for node in definition["nodes"] if node["type"] == "phase")
    # An unknown tool is never offered; the phase investigates through the knowledge tools instead.
    assert phase["config"]["tool_policy"]["allowlist"] == ["knowledge_search", "knowledge_read"]
    risks = version["publish_metadata"]["risks"]
    assert any("investigation placeholder" in risk for risk in risks)
    assert any("not_a_known_tool" in risk for risk in risks)
