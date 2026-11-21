"""API tests for orchestrator routes."""

import uuid

import pytest

from app.models import Session


@pytest.mark.asyncio
async def test_create_orchestrator_run_via_api(client, db, auth_headers, auth_user):
    session_id = str(uuid.uuid4())
    db.add(Session(id=session_id, user_id=auth_user.id, project_id=None, agent_type="change", metadata_={}))
    await db.flush()

    resp = await client.post(
        "/api/v1/orchestrator",
        json={
            "session_id": session_id,
            "pattern_type": "supervisor",
            "total_steps": 3,
            "max_iterations": 5,
        },
        headers=auth_headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["session_id"] == session_id
    assert data["pattern_type"] == "supervisor"
    assert data["status"] == "running"
    assert data["total_steps"] == 3
    assert data["max_iterations"] == 5


@pytest.mark.asyncio
async def test_list_orchestrator_runs(client, db, auth_headers, auth_user):
    session_id = str(uuid.uuid4())
    db.add(Session(id=session_id, user_id=auth_user.id, project_id=None, agent_type="change", metadata_={}))
    await db.flush()

    # Create a run via API
    resp = await client.post(
        "/api/v1/orchestrator",
        json={"session_id": session_id, "pattern_type": "sequential"},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    run_id = resp.json()["id"]

    resp = await client.get(f"/api/v1/orchestrator?session_id={session_id}", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) >= 1
    assert any(r["id"] == run_id for r in data)


@pytest.mark.asyncio
async def test_get_orchestrator_run_by_id(client, db, auth_headers, auth_user):
    session_id = str(uuid.uuid4())
    db.add(Session(id=session_id, user_id=auth_user.id, project_id=None, agent_type="change", metadata_={}))
    await db.flush()

    create_resp = await client.post(
        "/api/v1/orchestrator",
        json={"session_id": session_id, "pattern_type": "parallel"},
        headers=auth_headers,
    )
    run_id = create_resp.json()["id"]

    resp = await client.get(f"/api/v1/orchestrator/{run_id}", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == run_id
    assert data["pattern_type"] == "parallel"


@pytest.mark.asyncio
async def test_get_orchestrator_run_not_found(client, auth_headers):
    resp = await client.get("/api/v1/orchestrator/nonexistent-id", headers=auth_headers)
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_add_child_to_run(client, db, auth_headers, auth_user):
    session_id = str(uuid.uuid4())
    db.add(Session(id=session_id, user_id=auth_user.id, project_id=None, agent_type="change", metadata_={}))
    await db.flush()

    create_resp = await client.post(
        "/api/v1/orchestrator",
        json={"session_id": session_id, "pattern_type": "parallel"},
        headers=auth_headers,
    )
    run_id = create_resp.json()["id"]

    child_session_id = str(uuid.uuid4())
    db.add(Session(id=child_session_id, user_id=auth_user.id, project_id=None, agent_type="change", metadata_={}))
    await db.flush()
    resp = await client.post(
        "/api/v1/orchestrator/add-child",
        json={"run_id": run_id, "child_session_id": child_session_id},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert child_session_id in data["child_session_ids_json"]
    assert data["last_child_id"] == child_session_id


@pytest.mark.asyncio
async def test_merge_child_output(client, db, auth_headers, auth_user):
    session_id = str(uuid.uuid4())
    db.add(Session(id=session_id, user_id=auth_user.id, project_id=None, agent_type="change", metadata_={}))
    await db.flush()

    create_resp = await client.post(
        "/api/v1/orchestrator",
        json={"session_id": session_id, "pattern_type": "parallel"},
        headers=auth_headers,
    )
    run_id = create_resp.json()["id"]

    resp = await client.post(
        "/api/v1/orchestrator/merge-child",
        json={"run_id": run_id, "child_session_id": "child-1", "child_output": {"result": "output-1"}},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "children" in data["merged_output_json"]
    assert len(data["merged_output_json"]["children"]) == 1


@pytest.mark.asyncio
async def test_resolve_conflict(client, db, auth_headers, auth_user):
    session_id = str(uuid.uuid4())
    db.add(Session(id=session_id, user_id=auth_user.id, project_id=None, agent_type="change", metadata_={}))
    await db.flush()

    create_resp = await client.post(
        "/api/v1/orchestrator",
        json={"session_id": session_id, "pattern_type": "supervisor"},
        headers=auth_headers,
    )
    run_id = create_resp.json()["id"]

    resp = await client.post(
        "/api/v1/orchestrator/resolve-conflict",
        json={"run_id": run_id, "conflict_key": "api-design", "resolution": {"winner": "child-2"}, "notes": "Better API"},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["conflict_resolutions_json"]) == 1


@pytest.mark.asyncio
async def test_complete_orchestrator_run(client, db, auth_headers, auth_user):
    session_id = str(uuid.uuid4())
    db.add(Session(id=session_id, user_id=auth_user.id, project_id=None, agent_type="change", metadata_={}))
    await db.flush()

    create_resp = await client.post(
        "/api/v1/orchestrator",
        json={"session_id": session_id, "pattern_type": "single"},
        headers=auth_headers,
    )
    run_id = create_resp.json()["id"]

    resp = await client.post(
        "/api/v1/orchestrator/complete",
        json={"run_id": run_id, "status": "completed", "final_output": {"summary": "Done"}},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "completed"
    assert data["completed_at"] is not None


@pytest.mark.asyncio
async def test_cancel_orchestrator_run(client, db, auth_headers, auth_user):
    session_id = str(uuid.uuid4())
    db.add(Session(id=session_id, user_id=auth_user.id, project_id=None, agent_type="change", metadata_={}))
    await db.flush()

    create_resp = await client.post(
        "/api/v1/orchestrator",
        json={"session_id": session_id, "pattern_type": "supervisor"},
        headers=auth_headers,
    )
    run_id = create_resp.json()["id"]

    resp = await client.post(f"/api/v1/orchestrator/{run_id}/cancel", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "cancelled"


@pytest.mark.asyncio
async def test_submit_review(client, db, auth_headers, auth_user):
    session_id = str(uuid.uuid4())
    db.add(Session(id=session_id, user_id=auth_user.id, project_id=None, agent_type="change", metadata_={}))
    await db.flush()

    create_resp = await client.post(
        "/api/v1/orchestrator",
        json={"session_id": session_id, "pattern_type": "reviewer_critic"},
        headers=auth_headers,
    )
    run_id = create_resp.json()["id"]

    resp = await client.post(
        "/api/v1/orchestrator/submit-review",
        json={"run_id": run_id, "score": "pass", "notes": "Looks good"},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["last_review_score"] == "pass"
    assert data["revision_count"] == 1


@pytest.mark.asyncio
async def test_advance_step(client, db, auth_headers, auth_user):
    session_id = str(uuid.uuid4())
    db.add(Session(id=session_id, user_id=auth_user.id, project_id=None, agent_type="change", metadata_={}))
    await db.flush()

    create_resp = await client.post(
        "/api/v1/orchestrator",
        json={"session_id": session_id, "pattern_type": "sequential", "total_steps": 3},
        headers=auth_headers,
    )
    run_id = create_resp.json()["id"]

    resp = await client.post(
        f"/api/v1/orchestrator/advance-step?run_id={run_id}",
        headers=auth_headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["current_step_index"] == 1

    resp = await client.post(
        f"/api/v1/orchestrator/advance-step?run_id={run_id}",
        headers=auth_headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["current_step_index"] == 2
