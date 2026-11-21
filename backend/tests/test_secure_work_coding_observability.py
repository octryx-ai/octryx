from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from sqlalchemy import select

from app.models import AuditLog, Session, ToolCall, TurnTrace, UsageEvent, User, WorkCodingAuditEvent, WorkItem
from app.time_utils import utc_now


async def _seed_work_item_and_session(db, actor):
    item = WorkItem(
        source_type="jira",
        source_instance="risk",
        source_key="ACME-615",
        source_project_key="ACME",
        source_url="https://jira.example.test/browse/ACME-615",
        title="Cleaning Terraform and Helm Config",
        source_status="In Progress",
        work_state="implementation",
        sync_state="imported",
        labels_json=["octryx"],
    )
    db.add(item)
    chat_session = Session(
        user_id=actor.id,
        project_id=None,
        agent_type="coding",
        status="active",
        run_status="running",
        metadata_={},
    )
    db.add(chat_session)
    await db.flush()
    return item, chat_session


def _seed_started_audit_event(db, item, chat_session):
    started_at = utc_now()
    db.add(
        WorkCodingAuditEvent(
            work_item_id=item.id,
            event_type="agent_execution_started",
            title="Coding agent execution started",
            actor_kind="platform",
            evidence_json={"session_id": chat_session.id, "change_plan_id": "plan-1"},
            created_at=started_at,
        )
    )
    return started_at


def _seed_usage_events(db, actor, chat_session, started_at):
    db.add_all(
        [
            UsageEvent(
                session_id=chat_session.id,
                user_id=actor.id,
                provider="bedrock",
                model="amazon.nova-2-lite-v1:0",
                tokens_in=22000,
                tokens_out=150,
                cost=Decimal("0.010000"),
                request_id="req-1",
                created_at=started_at + timedelta(seconds=1),
            ),
            UsageEvent(
                session_id=chat_session.id,
                user_id=actor.id,
                provider="bedrock",
                model="amazon.nova-2-lite-v1:0",
                tokens_in=23000,
                tokens_out=120,
                cost=Decimal("0.011000"),
                request_id="req-2",
                created_at=started_at + timedelta(seconds=2),
            ),
        ]
    )


def _seed_tool_calls_trace_and_audit(db, actor, item, chat_session, started_at):
    repeated_parameters = {"path": "removed.txt"}
    for offset in range(3, 6):
        db.add(
            ToolCall(
                session_id=chat_session.id,
                tool_name="read_workspace_file",
                parameters=repeated_parameters,
                result={"content": "same evidence"},
                status="success",
                duration_ms=25,
                created_at=started_at + timedelta(seconds=offset),
            )
        )
    db.add_all(
        [
            ToolCall(
                session_id=chat_session.id,
                tool_name="edit_workspace_file",
                parameters={"path": "removed.txt"},
                result={"execution_event": {"kind": "file_edit", "status": "success"}},
                status="success",
                duration_ms=40,
                created_at=started_at + timedelta(seconds=6),
            ),
            ToolCall(
                session_id=chat_session.id,
                tool_name="run_cli_command",
                parameters={"command": "terraform validate"},
                result={"execution_event": {"kind": "validation", "status": "failed", "exit_code": 1}},
                status="failed",
                duration_ms=120,
                created_at=started_at + timedelta(seconds=7),
            ),
            TurnTrace(
                session_id=chat_session.id,
                provider="bedrock",
                model="amazon.nova-2-lite-v1:0",
                usage_json={"total_tokens": 23120},
                raw_output={"run_completion_reason": "repository evidence budget"},
                tool_trace_json=[],
                created_at=started_at + timedelta(seconds=8),
            ),
            AuditLog(
                user_id=actor.id,
                session_id=chat_session.id,
                action="secure_work.coding_policy_runtime_decision",
                resource_type="work_item",
                resource_id=item.id,
                details={"decision": {"status": "allowed"}},
                created_at=started_at + timedelta(seconds=9),
            ),
        ]
    )


async def test_work_item_coding_observability_aggregates_usage_tools_traces_and_audit(client, auth_headers, db):
    actor = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    item, chat_session = await _seed_work_item_and_session(db, actor)
    started_at = _seed_started_audit_event(db, item, chat_session)
    _seed_usage_events(db, actor, chat_session, started_at)
    _seed_tool_calls_trace_and_audit(db, actor, item, chat_session, started_at)
    await db.commit()

    response = await client.get(
        f"/api/v1/secure-work/work-items/{item.id}/coding-observability",
        headers=auth_headers,
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["schema"] == "coding_observability.v1"
    assert payload["source_key"] == "ACME-615"
    assert payload["summary"]["agent_session_count"] == 1
    assert payload["summary"]["llm_call_count"] == 2
    assert payload["summary"]["total_tokens"] == 45270
    assert payload["summary"]["total_cost"] == "0.021000"
    assert payload["summary"]["tool_call_count"] == 5
    assert payload["summary"]["failed_tool_call_count"] == 1
    assert payload["summary"]["mutation_event_count"] == 1
    assert payload["summary"]["validation_event_count"] == 1
    assert payload["summary"]["repeated_tool_call_count"] == 3
    assert payload["summary"]["status"] == "attention"
    assert payload["summary"]["latest_stop_reason"] == "repository evidence budget"
    assert payload["usage"]["total"]["tokens_total"] == 45270
    assert payload["usage"]["by_model"][0]["key"] == "bedrock / amazon.nova-2-lite-v1:0"
    assert payload["tools"]["by_kind"]["evidence"] == 3
    assert payload["tools"]["by_kind"]["mutation"] == 1
    assert payload["tools"]["by_kind"]["validation"] == 1
    assert payload["tools"]["repeated_calls"][0]["tool_name"] == "read_workspace_file"
    assert payload["audit"]["coding_events_by_type"]["agent_execution_started"] == 1
    assert payload["audit"]["platform_events_by_action"]["secure_work.coding_policy_runtime_decision"] == 1
    assert {entry["kind"] for entry in payload["timeline"]} >= {
        "llm_call",
        "tool_call",
        "turn_trace",
        "coding_audit",
        "platform_audit",
    }
