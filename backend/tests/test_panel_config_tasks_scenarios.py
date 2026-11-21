"""The admin tasks page (run history details) and scenario profile management."""

import uuid

import pytest
from sqlalchemy import select
from starlette.requests import Request

from app.models import Project, ScenarioProfile, Session, Task, TaskRun, User
from app.web._helpers._admin_tasks_context import _build_tasks_context
from tests.conftest import ADMIN_PASSWORD


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_admin_tasks_page_shows_run_history_details(client, db):
    login_resp = await client.post("/admin/login", data={"username": "admin", "password": ADMIN_PASSWORD})
    assert login_resp.status_code == 303

    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    project = (await db.execute(select(Project).where(Project.name == "acme-orders"))).scalar_one()
    session = Session(
        id=str(uuid.uuid4()),
        user_id=admin.id,
        project_id=project.id,
        agent_type="change",
        status="active",
    )
    db.add(session)
    await db.flush()

    task = Task(dispatch_binding="task_definition",
        id=str(uuid.uuid4()),
        project_id=project.id,
        name="History Watch",
        description="Watch history",
        task_type="agent_run",
        agent_type="change",
        schedule="*/15 * * * *",
        config={"prompt": "Process watched ticket."},
        is_active=True,
        owner_id=admin.id,
    )
    db.add(task)
    await db.flush()

    db.add(
        TaskRun(
            id=str(uuid.uuid4()),
            task_id=task.id,
            session_id=session.id,
            status="success",
            started_by=admin.id,
            input_={},
            output={
                "processed_tickets": [
                    {
                        "ticket_id": "RIVER-1",
                        "summary": "Automate this",
                        "session_id": session.id,
                    }
                ],
                "skipped_tickets": [{"ticket_id": "RIVER-2", "reason": "unchanged"}],
            },
        )
    )
    await db.commit()

    runs_resp = await client.get(f"/admin/chat/api/panel/tasks/{task.id}/runs")
    assert runs_resp.status_code == 200
    runs_payload = runs_resp.json()
    assert len(runs_payload) == 1
    run = runs_payload[0]
    assert run["session_id"] == session.id
    assert run["status"] == "success"

    request = Request({"type": "http", "method": "GET", "path": "/admin/tasks", "headers": []})
    tasks_context = await _build_tasks_context(request, db, user=admin, task_id=task.id)
    assert len(tasks_context["selected_task_runs"]) == 1
    selected_run = tasks_context["selected_task_runs"][0]
    assert selected_run["processed_tickets"][0]["ticket_id"] == "RIVER-1"
    assert selected_run["processed_tickets"][0]["session_id"] == session.id
    assert selected_run["skipped_tickets"][0]["ticket_id"] == "RIVER-2"
    assert selected_run["skipped_tickets"][0]["reason"] == "unchanged"


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_admin_panel_can_manage_scenario_profiles(client, db):
    login_resp = await client.post("/admin/login", data={"username": "admin", "password": ADMIN_PASSWORD})
    assert login_resp.status_code == 303

    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    project = (await db.execute(select(Project).where(Project.name == "acme-orders"))).scalar_one()

    list_resp = await client.get("/admin/chat/api/panel/scenarios")
    assert list_resp.status_code == 200

    create_resp = await client.post(
        "/admin/chat/api/panel/scenarios",
        json={
            "name": "Test Scenario",
            "description": "Scenario for summary routing",
            "project_id": project.id,
            "priority": 150,
            "match_config": {
                "route_reasons": ["summary_aggregation"],
                "required_domains": ["jira", "bitbucket", "confluence"],
            },
            "planner_config": {
                "include_system_context": False,
                "token_budget": 9000,
            },
            "execution_config": {
                "required_domains": ["jira", "bitbucket", "confluence"],
                "enforce_domain_coverage": True,
            },
            "is_active": True,
        },
    )
    assert create_resp.status_code == 200
    created = create_resp.json()
    assert created["name"] == "Test Scenario"
    assert created["owner_id"] == admin.id
    assert created["project_id"] == project.id
    assert created["planner_config"] == {"include_system_context": False, "token_budget": 9000}

    created_id = created["id"]
    stored = await db.get(ScenarioProfile, created_id)
    assert stored is not None
    assert stored.name == "Test Scenario"

    # Fields without effect are refused on write, with any value, before anything is applied.
    retired_resp = await client.put(
        f"/admin/chat/api/panel/scenarios/{created_id}",
        json={
            "description": "Must not be applied",
            "match_config": {"route_reasons": [], "keywords": []},
            "planner_config": {"tool_allowlist": ["bash"]},
        },
    )
    assert retired_resp.status_code == 422, retired_resp.text
    detail = retired_resp.json()["detail"]
    assert detail["code"] == "field_unsupported"
    assert detail["keys"] == ["match_config.keywords", "planner_config.tool_allowlist"]
    await db.refresh(stored)
    assert stored.description == "Scenario for summary routing"

    update_resp = await client.put(
        f"/admin/chat/api/panel/scenarios/{created_id}",
        json={
            "description": "Updated scenario profile",
            "priority": 175,
            "is_active": False,
        },
    )
    assert update_resp.status_code == 200
    updated = update_resp.json()
    assert updated["description"] == "Updated scenario profile"
    assert updated["priority"] == 175
    assert updated["is_active"] is False

    list_resp = await client.get("/admin/chat/api/panel/scenarios")
    assert list_resp.status_code == 200
    names = {profile["name"] for profile in list_resp.json()}
    assert "Test Scenario" in names

    delete_resp = await client.delete(f"/admin/chat/api/panel/scenarios/{created_id}")
    assert delete_resp.status_code == 200
    db.expire_all()
    deleted = (await db.execute(select(ScenarioProfile).where(ScenarioProfile.id == created_id))).scalar_one_or_none()
    assert deleted is None
