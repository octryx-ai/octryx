import uuid

import pytest
from sqlalchemy import select

from app.agent.core.context.run_context import prepare_agent_run
from app.models import Session, SessionEntity, User
from app.services.session.entity import (
    extract_session_entities_from_tool_result,
    list_session_entities,
    upsert_session_entities_from_tool_result,
)

_KUBECTL_PODS_STDOUT = """
        {
          "items": [
            {
              "metadata": {"name": "api-server-xyz", "namespace": "acme-orders"},
              "status": {
                "phase": "Running",
                "containerStatuses": [
                  {"name": "api", "restartCount": 3, "state": {"waiting": {"reason": "CrashLoopBackOff"}}}
                ]
              }
            },
            {
              "metadata": {"name": "worker-ok", "namespace": "acme-orders"},
              "status": {
                "phase": "Running",
                "containerStatuses": [{"name": "worker", "restartCount": 0, "state": {"running": {}}}]
              }
            }
          ]
        }
        """


def _jira_search_result(status: str) -> dict:
    return {
        "results": [
            {
                "key": "RIVER-42",
                "summary": "API timeout on payment flow",
                "status": {"name": status},
                "assignee": {"displayName": "Alice"},
            }
        ]
    }


async def _upsert_tool_result(db, session: Session, tool_name: str, result: dict) -> list[dict]:
    return await upsert_session_entities_from_tool_result(
        db,
        session_id=session.id,
        message_id=None,
        tool_name=tool_name,
        result=result,
    )


async def _jira_ticket_rows(db, session: Session) -> list[SessionEntity]:
    return (
        (
            await db.execute(
                select(SessionEntity).where(
                    SessionEntity.session_id == session.id,
                    SessionEntity.entity_type == "jira_ticket",
                    SessionEntity.entity_id == "RIVER-42",
                )
            )
        )
        .scalars()
        .all()
    )


@pytest.mark.asyncio
async def test_session_entities_extract_and_update_from_tool_results(db):
    user = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    session = Session(id=str(uuid.uuid4()), user_id=user.id)
    db.add(session)
    await db.flush()

    jira_entities = extract_session_entities_from_tool_result("search_jira_tickets", _jira_search_result("In Progress"))
    assert jira_entities[0]["entity_type"] == "jira_ticket"
    assert jira_entities[0]["entity_id"] == "RIVER-42"

    kubectl_result = {
        "command": ["kubectl", "-n", "acme-orders", "get", "pods", "-o", "json"],
        "stdout": _KUBECTL_PODS_STDOUT,
    }
    persisted = await _upsert_tool_result(db, session, "run_kubectl", kubectl_result)
    assert any(entity["entity_type"] == "k8s_pod" and entity["label"] == "api-server-xyz" for entity in persisted)

    branch_entities = await _upsert_tool_result(
        db,
        session,
        "prepare_bitbucket_repository",
        {
            "project_key": "RIVER",
            "repo_slug": "backend",
            "branch_name": "fix/timeout",
            "base_branch": "main",
        },
    )
    assert any(entity["entity_type"] == "git_branch" and entity["label"] == "fix/timeout" for entity in branch_entities)

    jira_upsert = await _upsert_tool_result(db, session, "search_jira_tickets", _jira_search_result("Done"))
    assert jira_upsert[0]["state_json"]["status"] == "Done"

    entities = await list_session_entities(db, session_id=session.id, limit=10)
    jira = next(item for item in entities if item["entity_type"] == "jira_ticket")
    assert jira["state_json"]["status"] == "Done"
    assert jira["times_seen"] >= 1

    rows = await _jira_ticket_rows(db, session)
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_prepare_agent_run_injects_entity_context(db):
    user = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    session = Session(id=str(uuid.uuid4()), user_id=user.id)
    db.add(session)
    await db.flush()
    db.add(
        SessionEntity(
            id=str(uuid.uuid4()),
            session_id=session.id,
            entity_type="jira_ticket",
            entity_id="RIVER-77",
            label="RIVER-77",
            state_json={"status": "In Progress", "assignee": "Alice"},
            relevance_score=5.0,
        )
    )
    await db.commit()

    async def fake_resolve_model_context_cap(_db, runtime_target_id=None):
        return None

    async def fake_resolve_control_plane_runtimes(_db, runtime_target_id=None):
        return []

    prepared = await prepare_agent_run(
        db=db,
        session_id=session.id,
        user_message="Investigate the payment incident",
        user_id=user.id,
        project_id=None,
        agent_type="diagnosis",
        runtime_target_id=None,
        thinking_level="light",
        agent_definition=None,
        parent_session_id=None,
        sub_agent_depth=0,
        workspace_root="/srv/octryx",
        resolve_model_context_cap=fake_resolve_model_context_cap,
        resolve_control_plane_runtimes_func=fake_resolve_control_plane_runtimes,
        filter_tool_definitions=lambda definitions, _allowlist: definitions,
        exclude_tool_definitions=lambda definitions, _blocked: definitions,
        trim_messages_to_budget=lambda messages, _budget: messages,
    )

    assert any(entity["entity_id"] == "RIVER-77" for entity in prepared.session_entities)
    assert "## Current Entities" in prepared.system_prompt
    assert "RIVER-77" in prepared.system_prompt
