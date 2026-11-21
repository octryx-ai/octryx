from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.models import (
    AgentDefinition,
    AgentStep,
    ExportPackage,
    ImportLog,
    Project,
    Skill,
    SkillVersion,
    Task,
    TaskDependency,
    TaskStep,
    User,
)
from app.services.export_package import create_export_package, import_package
from tests.action_agent_binding_support import bound_action_fields
from tests.conftest import ADMIN_PASSWORD
from tests.skill_catalog.support import publish_chat_skill


@pytest.mark.asyncio
async def test_export_package_service_round_trip_skill_agent_and_task(db):
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    project = (await db.execute(select(Project).where(Project.name == "acme-orders"))).scalar_one()

    skill, _version = await publish_chat_skill(
        db, "phase29-skill", approver_id=admin.id, description="Portable summary", category="ops", body="Do the thing",
        required_tools=("bash",), allowed_roles=("admin",),
    )

    agent = AgentDefinition(
        id=str(uuid.uuid4()),
        owner_id=admin.id,
        project_id=project.id,
        name="phase29-agent",
        description="portable agent",
        goal="Ship a fix",
        agent_type="change",
        thinking_level="deep",
        branch_prefix="codex",
        system_prompt="System",
        output_prompt="Output",
        require_self_review=True,
    )
    db.add(agent)
    await db.flush()
    db.add(
        AgentStep(
            id=str(uuid.uuid4()),
            agent_id=agent.id,
            position=1,
            name="Inspect",
            step_type="analysis",
            instructions="Inspect first",
        )
    )

    upstream = Task(dispatch_binding="task_definition",
        id=str(uuid.uuid4()),
        project_id=project.id,
        name="phase29-upstream",
        description="upstream dependency",
        task_type="agent_run",
        agent_type="diagnosis",
        owner_id=admin.id,
    )
    task = Task(dispatch_binding="task_definition",
        id=str(uuid.uuid4()),
        project_id=project.id,
        name="phase29-task",
        description="portable task",
        task_type="agent_run",
        agent_type="change",
        owner_id=admin.id,
        config={"repo": "acme-orders"},
    )
    db.add(upstream)
    db.add(task)
    await db.flush()
    step = TaskStep(
        id=str(uuid.uuid4()),
        task_id=task.id,
        position=1,
        name="Collect",
        step_type="analysis",
        instructions="Collect evidence",
    )
    step.allowed_tools_json = '["bash","git_status"]'
    db.add(step)
    db.add(TaskDependency(id=str(uuid.uuid4()), task_id=task.id, depends_on_task_id=upstream.id, condition="success"))
    await db.commit()

    skill_pkg = await create_export_package(db, current_user=admin, package_type="skill", entity_id=skill.id)
    agent_pkg = await create_export_package(db, current_user=admin, package_type="agent", entity_id=agent.id)
    task_pkg = await create_export_package(db, current_user=admin, package_type="task", entity_id=task.id)

    assert skill_pkg["package_type"] == "skill"
    skill_entity = skill_pkg["content_json"]["entity"]
    assert skill_entity["format"] == "skill_bundle" and skill_entity["version"] == 1
    assert "description: Portable summary" in skill_entity["files"]["SKILL.md"]
    assert skill_entity["extension"]["tools"]["platform_chat"]["required"] == ["bash"]
    assert agent_pkg["content_json"]["entity"]["steps"][0]["name"] == "Inspect"
    assert task_pkg["content_json"]["entity"]["dependencies"][0]["depends_on_task_name"] == "phase29-upstream"

    imported_skill = await import_package(
        db,
        current_user=admin,
        package_id=skill_pkg["id"],
        name_override="phase29-skill-imported",
    )
    # An agent always imports as a Global agent, whatever the target Workspace.
    project_id = project.id
    imported_agent = await import_package(
        db,
        current_user=admin,
        package_id=agent_pkg["id"],
        target_project_id=project_id,
        name_override="phase29-agent-imported",
    )
    imported_task = await import_package(
        db,
        current_user=admin,
        package_id=task_pkg["id"],
        target_project_id=project_id,
        name_override="phase29-task-imported",
    )

    # An imported skill is a catalog draft (publish after review), reported as a warning.
    assert imported_skill["status"] == "completed_with_warnings"
    assert imported_agent["status"] == "completed"
    assert imported_task["status"] == "completed"

    imported_skill_row = (await db.execute(select(Skill).where(Skill.name == "phase29-skill-imported"))).scalar_one()
    assert imported_skill_row.published_version_id is None
    draft = (await db.execute(select(SkillVersion).where(SkillVersion.skill_id == imported_skill_row.id))).scalar_one()
    assert draft.state == "draft" and draft.frontmatter["description"] == "Portable summary"
    assert draft.frontmatter["name"] == "phase29-skill-imported"
    assert draft.extension["tools"]["platform_chat"]["required"] == ["bash"]

    imported_agent_row = (
        await db.execute(
            select(AgentDefinition)
            .options(selectinload(AgentDefinition.steps))
            .where(AgentDefinition.name == "phase29-agent-imported")
        )
    ).scalar_one()
    assert imported_agent_row.project_id is None
    assert imported_agent_row.require_self_review is True
    assert len(imported_agent_row.steps) == 1
    assert imported_agent_row.steps[0].name == "Inspect"

    imported_task_row = (
        await db.execute(select(Task).options(selectinload(Task.steps)).where(Task.name == "phase29-task-imported"))
    ).scalar_one()
    assert imported_task_row.config == {"repo": "acme-orders"}
    assert len(imported_task_row.steps) == 1
    dependency = (
        await db.execute(select(TaskDependency).where(TaskDependency.task_id == imported_task_row.id))
    ).scalar_one()
    assert dependency.depends_on_task_id == upstream.id

    export_count = (await db.execute(select(ExportPackage))).scalars().all()
    import_count = (await db.execute(select(ImportLog))).scalars().all()
    assert len(export_count) == 3
    assert len(import_count) == 3  # one log row per import


@pytest.mark.asyncio
async def test_import_package_rejects_checksum_mismatch(db):
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    package_json = {
        "package_type": "skill",
        "content_json": {
            "format_version": 1,
            "package_type": "skill",
            "entity": {
                "format": "skill_bundle",
                "name": "bad-skill",
                "category": "Utility",
                "files": {"SKILL.md": "---\nname: bad-skill\ndescription: Bad\n---\n\nHello\n"},
                "extension": {},
            },
            "source": {"entity_id": "demo"},
        },
        "checksum": "deadbeef",
    }

    with pytest.raises(Exception) as exc_info:
        await import_package(db, current_user=admin, package_json=package_json)

    assert "checksum" in str(exc_info.value).lower()


@pytest.mark.asyncio
async def test_export_package_api_and_panel_flow(client, auth_headers, db):
    project = (await db.execute(select(Project).where(Project.name == "acme-orders"))).scalar_one()

    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    skill, _version = await publish_chat_skill(db, "phase29-api-skill", approver_id=admin.id,
                                               description="API roundtrip skill", body="content")
    await db.commit()
    skill_id = skill.id

    export_resp = await client.post(
        "/api/v1/packages/export",
        headers=auth_headers,
        json={"package_type": "skill", "entity_id": skill_id},
    )
    assert export_resp.status_code == 200, export_resp.text
    package_payload = export_resp.json()
    assert package_payload["package_type"] == "skill"

    import_resp = await client.post(
        "/api/v1/packages/import",
        headers=auth_headers,
        json={
            "package_id": package_payload["id"],
            "name_override": "phase29-api-skill-imported",
        },
    )
    assert import_resp.status_code == 200, import_resp.text
    assert import_resp.json()["status"] == "completed_with_warnings"  # imported as a catalog draft

    login_resp = await client.post("/admin/login", data={"username": "admin", "password": ADMIN_PASSWORD})
    assert login_resp.status_code == 303

    task_resp = await client.post(
        "/admin/chat/api/panel/tasks",
        json={
            "name": "phase29-panel-task",
            "description": "",
            "task_type": "agent_run",
            "agent_type": "diagnosis",
            "project_id": project.id,
            **await bound_action_fields(db, project.id),
        },
    )
    assert task_resp.status_code == 200, task_resp.text
    task_id = task_resp.json()["id"]

    panel_export_resp = await client.post(
        "/admin/chat/api/panel/export-packages",
        json={"package_type": "task", "entity_id": task_id},
    )
    assert panel_export_resp.status_code == 200, panel_export_resp.text
    panel_package = panel_export_resp.json()

    panel_import_resp = await client.post(
        "/admin/chat/api/panel/import-packages",
        json={
            "package_id": panel_package["id"],
            "target_project_id": project.id,
            "name_override": "phase29-panel-task-imported",
        },
    )
    assert panel_import_resp.status_code == 200, panel_import_resp.text
    assert panel_import_resp.json()["status"] == "completed"

    exports_list = await client.get("/admin/chat/api/panel/export-packages")
    assert exports_list.status_code == 200
    assert any(row["id"] == panel_package["id"] for row in exports_list.json())

    imports_list = await client.get("/admin/chat/api/panel/import-log")
    assert imports_list.status_code == 200
    assert any(row["id"] == panel_import_resp.json()["id"] for row in imports_list.json())
