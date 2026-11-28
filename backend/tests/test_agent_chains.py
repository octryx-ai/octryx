from __future__ import annotations

import asyncio
import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models import AgentChainRun, Project, Session, User
from app.services.agent_chain import execute_agent_chain, templates
from tests.scripted_pool_support import scripted_turns  # noqa: F401 - fixture

pytestmark = pytest.mark.usefixtures("scripted_turns")


@pytest.mark.asyncio
async def test_agent_chain_template_api_crud_and_run(client, auth_headers, db, monkeypatch, scripted_turns):  # noqa: F811
    project = (await db.execute(select(Project).where(Project.name == "acme-orders"))).scalar_one()

    async def answer(user_message):
        return f"processed:{user_message}"

    scripted_turns["default"] = answer

    create_resp = await client.post(
        "/api/v1/agent-chains/templates",
        headers=auth_headers,
        json={
            "name": "Triaged handover",
            "description": "Route triage into review",
            "project_id": project.id,
            "steps": [
                {
                    "id": "triage",
                    "name": "Triage",
                    "agent_type": "diagnosis",
                    "input_mapping": {"template": "Triage {ticket}"},
                    "output_mapping": {"key": "triage_summary"},
                },
                {
                    "id": "review",
                    "name": "Review",
                    "agent_type": "summary",
                    "input_mapping": {"template": "Review {triage_summary}"},
                    "output_mapping": {"key": "review_summary"},
                },
            ],
        },
    )
    assert create_resp.status_code == 200, create_resp.text
    created = create_resp.json()
    assert created["step_count"] == 2

    list_resp = await client.get("/api/v1/agent-chains/templates", headers=auth_headers)
    assert list_resp.status_code == 200
    assert any(item["id"] == created["id"] for item in list_resp.json())

    update_resp = await client.put(
        f"/api/v1/agent-chains/templates/{created['id']}",
        headers=auth_headers,
        json={"description": "Updated chain description"},
    )
    assert update_resp.status_code == 200, update_resp.text
    assert update_resp.json()["description"] == "Updated chain description"

    run_resp = await client.post(
        f"/api/v1/agent-chains/templates/{created['id']}/run",
        headers=auth_headers,
        json={"input_payload": {"ticket": "RIVER-42"}},
    )
    assert run_resp.status_code == 200, run_resp.text
    run_payload = run_resp.json()
    assert run_payload["status"] == "completed"
    assert len(run_payload["step_results"]) == 2
    assert run_payload["step_results"][0]["content"] == "processed:Triage RIVER-42"
    assert run_payload["step_results"][1]["prompt"] == "Review processed:Triage RIVER-42"
    assert run_payload["output_payload"]["triage_summary"] == "processed:Triage RIVER-42"
    assert run_payload["output_payload"]["review_summary"] == "processed:Review processed:Triage RIVER-42"

    stored_run = await db.get(AgentChainRun, run_payload["id"])
    assert stored_run is not None
    assert stored_run.status == "completed"

    child_sessions = (
        (
            await db.execute(
                select(Session).where(Session.metadata_["agent_chain_run_id"].as_string() == run_payload["id"])
            )
        )
        .scalars()
        .all()
    )
    assert len(child_sessions) == 2

    run_list_resp = await client.get(
        f"/api/v1/agent-chains/runs?template_id={created['id']}",
        headers=auth_headers,
    )
    assert run_list_resp.status_code == 200
    assert any(item["id"] == run_payload["id"] for item in run_list_resp.json())

    run_read_resp = await client.get(f"/api/v1/agent-chains/runs/{run_payload['id']}", headers=auth_headers)
    assert run_read_resp.status_code == 200
    assert run_read_resp.json()["id"] == run_payload["id"]

    delete_resp = await client.delete(f"/api/v1/agent-chains/templates/{created['id']}", headers=auth_headers)
    assert delete_resp.status_code == 200
    assert delete_resp.json()["status"] == "deleted"


@pytest.mark.asyncio
async def test_execute_agent_chain_parallel_group_runs_concurrently_and_feeds_context(reset_db, monkeypatch,
                                                                                     scripted_turns):  # noqa: F811
    db = reset_db
    project = (await db.execute(select(Project).where(Project.name == "acme-orders"))).scalar_one()
    current_user = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    parent_session_id = str(uuid.uuid4())

    template = await templates.create_agent_chain_template(
        db,
        current_user=current_user,
        payload={
            "name": "Parallel incident chain",
            "project_id": project.id,
            "steps": [
                {
                    "id": "branch_a",
                    "name": "Branch A",
                    "agent_type": "diagnosis",
                    "execution_mode": "parallel",
                    "parallel_group": "fanout",
                    "input_mapping": {"template": "Check pods {incident}"},
                    "output_mapping": {"key": "pods_result"},
                },
                {
                    "id": "branch_b",
                    "name": "Branch B",
                    "agent_type": "diagnosis",
                    "execution_mode": "parallel",
                    "parallel_group": "fanout",
                    "input_mapping": {"template": "Check logs {incident}"},
                    "output_mapping": {"key": "logs_result"},
                },
                {
                    "id": "merge",
                    "name": "Merge",
                    "agent_type": "summary",
                    "input_mapping": {"template": "Merge {pods_result} + {logs_result}"},
                    "output_mapping": {"key": "final_summary"},
                },
            ],
        },
    )

    active = 0
    max_active = 0

    async def answer(user_message):
        nonlocal active, max_active
        active += 1
        max_active = max(max_active, active)
        await asyncio.sleep(0.2)
        active -= 1
        return f"done:{user_message}"

    scripted_turns["default"] = answer
    session_factory = async_sessionmaker(db.bind, class_=AsyncSession, expire_on_commit=False)

    run_payload = await execute_agent_chain(
        db,
        template_id=template["id"],
        current_user=current_user,
        input_payload={"incident": "INC-777"},
        parent_session_id=parent_session_id,
        session_factory=session_factory,
    )

    assert run_payload["status"] == "completed"
    assert len(run_payload["step_results"]) == 3
    assert max_active >= 2
    assert run_payload["output_payload"]["pods_result"] == "done:Check pods INC-777"
    assert run_payload["output_payload"]["logs_result"] == "done:Check logs INC-777"
    assert run_payload["step_results"][-1]["prompt"] == "Merge done:Check pods INC-777 + done:Check logs INC-777"

    sessions = (
        (
            await db.execute(
                select(Session).where(Session.metadata_["agent_chain_run_id"].as_string() == run_payload["id"])
            )
        )
        .scalars()
        .all()
    )
    assert len(sessions) == 3
    assert {session.parent_session_id for session in sessions} == {parent_session_id}
