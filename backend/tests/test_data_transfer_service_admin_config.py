"""The admin config backup excludes threads, restores configurable content and selected sections, keeps protected project config out of normal projects and drops connection keys."""

from __future__ import annotations

import json
import uuid
from pathlib import Path

import pytest
from sqlalchemy import select

from app.models import AgentDefinition, AgentStep, Message, Project, Session, Skill, Task, TaskStep, User
from app.services.data_transfer import create_data_export_job, create_data_import_job
from tests.skill_catalog.support import publish_chat_skill


async def _seed_backup_source(db, admin, project) -> Project:
    """Seeds a thread, a task, an agent and a skill on the source project; returns the restore target."""
    session = Session(id=str(uuid.uuid4()), user_id=admin.id, project_id=project.id, agent_type="diagnosis")
    db.add(session)
    await db.flush()
    db.add(Message(id=str(uuid.uuid4()), session_id=session.id, role="user", content="do not export me"))
    task = Task(dispatch_binding="task_definition",
        id=str(uuid.uuid4()),
        project_id=project.id,
        name="phase210-admin-backup-task",
        description="backup task",
        task_type="agent_run",
        agent_type="diagnosis",
        owner_id=admin.id,
    )
    agent = AgentDefinition(
        id=str(uuid.uuid4()),
        owner_id=admin.id,
        project_id=project.id,
        name="phase210-admin-backup-agent",
        description="backup agent",
        goal="backup",
    )
    await publish_chat_skill(db, "phase210-admin-backup-skill", approver_id=admin.id, description="backup skill",
                             body="do it")
    db.add_all([task, agent])
    await db.flush()
    db.add(TaskStep(id=str(uuid.uuid4()), task_id=task.id, position=1, name="step-a", step_type="analysis"))
    db.add(AgentStep(id=str(uuid.uuid4()), agent_id=agent.id, position=1, name="agent-step", step_type="analysis"))
    target = Project(
        id=str(uuid.uuid4()),
        name="phase210-admin-backup-target",
        description="target before restore",
        config={},
    )
    db.add(target)
    await db.commit()
    return target


async def _export_admin_config_backup(db, admin, project_id: str) -> dict:
    return await create_data_export_job(
        db,
        current_user=admin,
        export_type="admin_config_backup",
        scope_type="project",
        scope_id=project_id,
        format_name="json",
    )


async def _import_admin_config_backup(db, admin, payload: dict, target_project_id: str, **extra) -> dict:
    return await create_data_import_job(
        db,
        current_user=admin,
        import_type="admin_config_backup",
        source_format="json",
        payload_json=payload,
        payload_text=None,
        target_project_id=target_project_id,
        overwrite_existing=True,
        **extra,
    )


async def _restored_task_and_agent(db, target_id: str, task_name: str, agent_name: str):
    restored_task = (
        await db.execute(select(Task).where(Task.project_id == target_id, Task.name == task_name))
    ).scalar_one_or_none()
    restored_agent = (
        await db.execute(
            select(AgentDefinition).where(
                AgentDefinition.project_id == target_id,
                AgentDefinition.name == agent_name,
            )
        )
    ).scalar_one_or_none()
    return restored_task, restored_agent


@pytest.mark.asyncio
async def test_admin_config_backup_excludes_threads_and_restores_configurable_content(db):
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    project = (await db.execute(select(Project).where(Project.name == "acme-orders"))).scalar_one()
    project.config = {"coding_workflow": {"enabled": True}}

    target = await _seed_backup_source(db, admin, project)

    export_job = await _export_admin_config_backup(db, admin, project.id)

    assert export_job["status"] == "completed"
    payload = json.loads(Path(export_job["file_url"]).read_text(encoding="utf-8"))
    assert payload["export_type"] == "admin_config_backup"
    assert payload["manifest"]["included_sections"] == ["project_config", "tasks", "agents", "skills"]
    assert "sessions" in payload["manifest"]["excluded_sections"]
    assert "messages" in payload["manifest"]["excluded_sections"]
    assert "sessions" not in payload
    assert "messages" not in payload
    assert "task_runs" not in payload
    assert "do not export me" not in json.dumps(payload)

    import_job = await _import_admin_config_backup(db, admin, payload, target.id)

    # The existing platform-wide skill is kept (overwrite_existing does not reach skills).
    # The agent row is restored as a Global agent, never into the Workspace.
    assert import_job["status"] == "completed", import_job["errors"]
    assert "phase210-admin-backup-skill" in import_job["summary"]["skills_kept"]
    await db.refresh(target)
    assert target.config == {"coding_workflow": {"enabled": True}}
    restored_task, restored_agent = await _restored_task_and_agent(
        db, target.id, "phase210-admin-backup-task", "phase210-admin-backup-agent"
    )
    assert restored_task is not None
    assert restored_agent is None
    assert (await db.execute(select(AgentDefinition).where(
        AgentDefinition.project_id.is_(None), AgentDefinition.name == "phase210-admin-backup-agent"))).scalar_one()


@pytest.mark.asyncio
async def test_admin_config_backup_can_restore_selected_sections(db):
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    project = (await db.execute(select(Project).where(Project.name == "acme-orders"))).scalar_one()
    task = Task(dispatch_binding="task_definition",
        id=str(uuid.uuid4()),
        project_id=project.id,
        name="phase210-partial-restore-task",
        task_type="agent_run",
        agent_type="diagnosis",
        owner_id=admin.id,
    )
    agent = AgentDefinition(
        id=str(uuid.uuid4()),
        owner_id=admin.id,
        project_id=project.id,
        name="phase210-partial-restore-agent",
        goal="backup",
    )
    skill, _version = await publish_chat_skill(db, "phase210-partial-restore-skill", approver_id=admin.id,
                                               description="backup skill", body="do it")
    target = Project(id=str(uuid.uuid4()), name="phase210-partial-restore-target", config={})
    db.add_all([task, agent, target])
    await db.commit()

    export_job = await _export_admin_config_backup(db, admin, project.id)
    payload = json.loads(Path(export_job["file_url"]).read_text(encoding="utf-8"))
    # The original leaves under another name, so the restore creates the skill again.
    skill.name = "phase210-partial-restore-skill-before"
    await db.commit()

    import_job = await _import_admin_config_backup(db, admin, payload, target.id, restore_sections=["skills"])

    assert import_job["status"] == "completed"
    assert import_job["summary"]["restore_sections"] == ["skills"]
    assert import_job["summary"]["skill_count"] >= 1
    restored_skill = (
        await db.execute(select(Skill).where(Skill.name == "phase210-partial-restore-skill"))
    ).scalar_one_or_none()
    assert restored_skill is not None and restored_skill.id != skill.id
    restored_task, restored_agent = await _restored_task_and_agent(
        db, target.id, "phase210-partial-restore-task", "phase210-partial-restore-agent"
    )
    assert restored_skill is not None
    assert restored_task is None
    assert restored_agent is None


@pytest.mark.asyncio
async def test_admin_config_backup_does_not_restore_protected_project_config_into_normal_project(db):
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    protected_source = Project(
        id=str(uuid.uuid4()),
        name="phase210-master-source",
        description="protected source",
        config={"coding_workflow_templates": {"security_sensitive_change": {"label": "Master Security"}}},
        is_system=True,
    )
    target = Project(
        id=str(uuid.uuid4()),
        name="phase210-normal-target",
        description="normal target",
        config={"existing": True},
        is_system=False,
    )
    db.add_all([protected_source, target])
    await db.commit()

    export_job = await create_data_export_job(
        db,
        current_user=admin,
        export_type="admin_config_backup",
        scope_type="project",
        scope_id=protected_source.id,
        format_name="json",
    )
    payload = json.loads(Path(export_job["file_url"]).read_text(encoding="utf-8"))

    import_job = await create_data_import_job(
        db,
        current_user=admin,
        import_type="admin_config_backup",
        source_format="json",
        payload_json=payload,
        payload_text=None,
        target_project_id=target.id,
        overwrite_existing=True,
        restore_sections=["project_config"],
    )

    await db.refresh(target)
    assert import_job["status"] == "completed"
    assert import_job["summary"]["project_config_updated"] is False
    assert import_job["summary"]["project_config_skip_reason"] == "protected_project_mismatch"
    assert target.config == {"existing": True}


@pytest.mark.asyncio
async def test_admin_config_restore_drops_and_names_connection_keys(db):
    """The restore applies the write paths' rule: no connection key it would
    set reaches Project.config; the other keys are restored."""
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    source = Project(id=str(uuid.uuid4()), name="r9-restore-source", description="source", config={
        "jira_url": "https://svc:pw@jira.example.test", "jira_token": "plain", "kubeconfig_path": "/tmp/k",
        "grafana_url": "https://grafana.example.test", "k8s_context": "ws", "existing": False,
    })
    target = Project(id=str(uuid.uuid4()), name="r9-restore-target", description="target",
                     config={"existing": True})
    db.add_all([source, target])
    await db.commit()
    export_job = await create_data_export_job(db, current_user=admin, export_type="admin_config_backup",
                                              scope_type="project", scope_id=source.id, format_name="json")
    payload = json.loads(Path(export_job["file_url"]).read_text(encoding="utf-8"))

    import_job = await create_data_import_job(
        db, current_user=admin, import_type="admin_config_backup", source_format="json", payload_json=payload,
        payload_text=None, target_project_id=target.id, overwrite_existing=True, restore_sections=["project_config"],
    )

    await db.refresh(target)
    assert import_job["status"] == "completed" and import_job["summary"]["project_config_updated"] is True
    assert import_job["summary"]["project_config_connection_keys_dropped"] == [
        "grafana_url", "jira_token", "jira_url", "kubeconfig_path"]
    assert target.config == {"k8s_context": "ws", "existing": False}
    assert "pw" not in str(import_job["summary"])
