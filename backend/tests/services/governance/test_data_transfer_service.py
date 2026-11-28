"""Project backup and GDPR exports, refused retired knowledge import and export types, and the data transfer API flow."""

from __future__ import annotations

import json
import uuid
import zipfile
from pathlib import Path

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.models import AgentDefinition, AgentStep, Message, Project, Session, Task, TaskStep
from app.services.data_transfer import create_data_export_job, create_data_import_job
from tests.skill_catalog.support import publish_chat_skill


@pytest.mark.asyncio
async def test_project_backup_export_includes_tasks_agents_and_skills_and_no_knowledge(db, auth_user):
    project = (await db.execute(select(Project).where(Project.name == "acme-orders"))).scalar_one()

    task = Task(dispatch_binding="task_definition",
        id=str(uuid.uuid4()),
        project_id=project.id,
        name="phase210-task",
        description="backup task",
        task_type="agent_run",
        agent_type="diagnosis",
        owner_id=auth_user.id,
    )
    agent = AgentDefinition(
        id=str(uuid.uuid4()),
        owner_id=auth_user.id,
        project_id=project.id,
        name="phase210-agent",
        description="backup agent",
        goal="backup",
    )
    await publish_chat_skill(db, "phase210-skill", approver_id=auth_user.id, description="backup skill", body="do it")
    db.add(task)
    db.add(agent)
    await db.flush()
    db.add(TaskStep(id=str(uuid.uuid4()), task_id=task.id, position=1, name="step-a", step_type="analysis"))
    db.add(AgentStep(id=str(uuid.uuid4()), agent_id=agent.id, position=1, name="agent-step", step_type="analysis"))
    await db.commit()

    job = await create_data_export_job(
        db,
        current_user=auth_user,
        export_type="project_backup",
        scope_type="project",
        scope_id=project.id,
        format_name="json",
    )

    assert job["status"] == "completed"
    payload = json.loads(Path(job["file_url"]).read_text(encoding="utf-8"))
    assert payload["project"]["id"] == project.id
    # The KnowledgeMap section is retired with that store.
    assert "knowledge" not in payload
    assert any(row["entity"]["name"] == "phase210-task" for row in payload["tasks"])
    assert any(row["entity"]["name"] == "phase210-agent" for row in payload["agents"])
    assert any(row["entity"]["name"] == "phase210-skill" for row in payload["skills"])


@pytest.mark.asyncio
async def test_user_gdpr_export_creates_zip_with_user_sessions_and_messages(db, auth_user):
    session = Session(id=str(uuid.uuid4()), user_id=auth_user.id, agent_type="diagnosis", status="completed")
    db.add(session)
    await db.flush()
    db.add(Message(id=str(uuid.uuid4()), session_id=session.id, role="user", content="hello"))
    await db.commit()

    job = await create_data_export_job(
        db,
        current_user=auth_user,
        export_type="user_data_gdpr",
        scope_type="user",
        scope_id=auth_user.id,
        format_name="zip",
    )

    assert job["status"] == "completed"
    with zipfile.ZipFile(job["file_url"], "r") as archive:
        names = set(archive.namelist())
        assert {"user.json", "sessions.json", "messages.json"}.issubset(names)
        user_payload = json.loads(archive.read("user.json").decode("utf-8"))
        assert user_payload["id"] == auth_user.id


@pytest.mark.asyncio
async def test_retired_knowledge_import_and_export_types_are_refused(db, auth_user):
    project = (await db.execute(select(Project).where(Project.name == "acme-orders"))).scalar_one()
    with pytest.raises(HTTPException) as refused_import:
        await create_data_import_job(
            db,
            current_user=auth_user,
            import_type="knowledge",
            source_format="json",
            payload_json=[],
            payload_text=None,
            target_project_id=project.id,
        )
    assert refused_import.value.status_code == 400
    with pytest.raises(HTTPException) as refused_export:
        await create_data_export_job(
            db,
            current_user=auth_user,
            export_type="knowledge_export",
            scope_type="project",
            scope_id=project.id,
            format_name="json",
        )
    assert refused_export.value.status_code == 400


@pytest.mark.asyncio
async def test_data_transfer_api_flow(client, auth_headers, db):
    project = (await db.execute(select(Project).where(Project.name == "acme-orders"))).scalar_one()

    export_resp = await client.post(
        "/api/v1/data/exports",
        headers=auth_headers,
        json={
            "export_type": "agent_definitions",
            "scope_type": "project",
            "scope_id": project.id,
            "format": "json",
        },
    )
    assert export_resp.status_code == 200, export_resp.text
    export_job = export_resp.json()
    assert export_job["status"] == "completed"

    import_resp = await client.post(
        "/api/v1/data/imports",
        headers=auth_headers,
        json={
            "import_type": "skills",
            "source_format": "json",
            "payload_json": [
                {
                    "entity": {
                        "format": "skill_bundle",
                        "name": "phase210-imported-skill",
                        "category": "Utility",
                        "files": {"SKILL.md": "---\nname: phase210-imported-skill\ndescription: Imported\n---\n\nHello\n"},
                        "extension": {},
                    }
                }
            ],
            "overwrite_existing": False,
        },
    )
    assert import_resp.status_code == 200, import_resp.text
    assert import_resp.json()["status"] == "completed"

    # /api/v1/data is the one path; the panel duplicates are gone.
    imports_list = await client.get("/api/v1/data/imports", headers=auth_headers)
    assert imports_list.status_code == 200
    assert any(row["id"] == import_resp.json()["id"] for row in imports_list.json())
    download = await client.get(f"/api/v1/data/exports/{export_job['id']}/download", headers=auth_headers)
    assert download.status_code == 200
    for path in ("/admin/chat/api/panel/data-exports", "/admin/chat/api/panel/data-imports"):
        assert (await client.get(path, headers=auth_headers)).status_code in {404, 405}
