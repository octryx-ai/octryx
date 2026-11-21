"""Tests for chat turn preparation, preflight and explicit agent selection."""

import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.models import ControlPlaneRuntimeTarget, Project, User, UserProject, WorkspacePolicy
from app.services.workspace_composition import seed_workspace_bundle_foundation
from tests.turn_preparation_support import prepare_chat_turn


@pytest.mark.asyncio
async def test_prepare_chat_turn_selected_only_without_an_allowed_runtime_is_refused(db):
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    project = Project(id=str(uuid.uuid4()), name="selected-runtime-project", config={}, is_active=True)
    db.add(project)
    await db.commit()

    await seed_workspace_bundle_foundation(db, workspace_id=project.id)
    policy = (await db.execute(select(WorkspacePolicy).where(WorkspacePolicy.workspace_id == project.id))).scalar_one()
    policy.runtime_policy = {"runtime_assignment_mode": "selected_only"}
    await db.commit()

    # With nothing selected, the automatic chain would answer on a runtime
    # the Workspace does not allow, so the turn is refused with a code instead.
    with pytest.raises(HTTPException) as refused:
        await prepare_chat_turn(
            db=db,
            user=admin,
            prompt="Migriere spring-petclinic-rest zu Java 25 und Spring Boot 4.0.3 mit OpenRewrite.",
            project_id=project.id,
            agent_type="coding",
            agent_type_explicit=True,
        )
    assert refused.value.status_code == 403
    assert "No active runtime is allowed for this Workspace" in str(refused.value.detail)


@pytest.mark.asyncio
async def test_prepare_chat_turn_rejects_project_for_non_member(db):
    user = User(
        id=str(uuid.uuid4()),
        username="support-outsider",
        email="support-outsider@example.com",
        password_hash="x",
        is_active=True,
    )
    project = Project(id=str(uuid.uuid4()), name="restricted-support-project", config={}, is_active=True)
    db.add_all([user, project])
    await db.commit()

    with pytest.raises(HTTPException) as exc_info:
        await prepare_chat_turn(
            db=db,
            user=user,
            prompt="What is known about this support project?",
            project_id=project.id,
            project_id_explicit=True,
            agent_type="chat",
        )

    assert exc_info.value.status_code == 404  # a non-member gets the answer of an unknown Workspace


@pytest.mark.asyncio
async def test_prepare_chat_turn_auto_selects_only_assigned_project(db):
    user = User(
        id=str(uuid.uuid4()),
        username="single-project-support",
        email="single-project-support@example.com",
        password_hash="x",
        is_active=True,
    )
    project = Project(id=str(uuid.uuid4()), name="single support project", config={}, is_active=True)
    db.add_all([user, project])
    await db.flush()
    db.add(UserProject(user_id=user.id, project_id=project.id, role="support"))
    await db.commit()

    session, _runtime_target_id, _thinking_level, _agent_payload = await prepare_chat_turn(
        db=db,
        user=user,
        prompt="What do you know about this project?",
        project_id="",
        agent_type="chat",
    )

    assert session.project_id == project.id


@pytest.mark.asyncio
async def test_prepare_chat_turn_requires_project_selection_when_multiple_projects_are_assigned(db):
    user = User(
        id=str(uuid.uuid4()),
        username="multi-project-support",
        email="multi-project-support@example.com",
        password_hash="x",
        is_active=True,
    )
    first_project = Project(id=str(uuid.uuid4()), name="multi support a", config={}, is_active=True)
    second_project = Project(id=str(uuid.uuid4()), name="multi support b", config={}, is_active=True)
    db.add_all([user, first_project, second_project])
    await db.flush()
    db.add_all(
        [
            UserProject(user_id=user.id, project_id=first_project.id, role="support"),
            UserProject(user_id=user.id, project_id=second_project.id, role="support"),
        ]
    )
    await db.commit()

    with pytest.raises(HTTPException) as exc_info:
        await prepare_chat_turn(
            db=db,
            user=user,
            prompt="What do you know?",
            project_id="",
            agent_type="chat",
        )

    assert exc_info.value.status_code == 400
    assert "project" in str(exc_info.value.detail).lower()


@pytest.mark.asyncio
async def test_prepare_chat_turn_selected_only_runtime_rejects_explicit_unassigned_runtime(db):
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    runtime_target = (await db.execute(select(ControlPlaneRuntimeTarget))).scalars().first()
    assert runtime_target is not None
    project = Project(id=str(uuid.uuid4()), name="selected-runtime-explicit-project", config={}, is_active=True)
    db.add(project)
    await db.commit()

    await seed_workspace_bundle_foundation(db, workspace_id=project.id)
    policy = (await db.execute(select(WorkspacePolicy).where(WorkspacePolicy.workspace_id == project.id))).scalar_one()
    policy.runtime_policy = {"runtime_assignment_mode": "selected_only"}
    await db.commit()

    with pytest.raises(HTTPException) as exc_info:
        await prepare_chat_turn(
            db=db,
            user=admin,
            prompt="Run this on the requested runtime.",
            project_id=project.id,
            runtime_target_id=runtime_target.id,
            runtime_target_id_explicit=True,
            agent_type="chat",
        )

    assert exc_info.value.status_code == 403
    assert "runtime" in str(exc_info.value.detail).lower()


@pytest.mark.asyncio
async def test_prepare_chat_turn_rejects_unknown_explicit_runtime_target(db):
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()

    with pytest.raises(HTTPException) as exc_info:
        await prepare_chat_turn(
            db=db,
            user=admin,
            prompt="Run this on the selected runtime.",
            runtime_target_id=str(uuid.uuid4()),
            runtime_target_id_explicit=True,
            agent_type="chat",
        )

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "Runtime target not found"
