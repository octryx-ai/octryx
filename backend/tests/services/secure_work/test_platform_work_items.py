"""Platform-native work items: LLM-creatable epics/tasks that never sync to
Jira, with session-linked handover context between workers."""

from __future__ import annotations

import uuid
from datetime import timedelta

import pytest
from sqlalchemy import select

from app.models import AuditLog, Message, Project, Session, User
from app.services.secure_work.jira.jira_state_sync import execute_jira_state_sync
from app.services.secure_work.platform_item_context import build_work_item_context
from app.services.secure_work.platform_item_sessions import link_session_to_work_item
from app.services.secure_work.platform_items import add_work_item_note, create_platform_work_item
from app.time_utils import utc_now


async def _admin_and_project(db):
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    project = (await db.execute(select(Project).where(Project.name == "acme-orders"))).scalar_one()
    return admin, project


@pytest.mark.asyncio
async def test_create_platform_epic_and_task_with_sequential_keys(db):
    admin, project = await _admin_and_project(db)
    epic = await create_platform_work_item(
        db,
        current_user=admin,
        project_id=project.id,
        title="Rework knowledge retrieval",
        issue_type="epic",
    )
    task = await create_platform_work_item(
        db,
        current_user=admin,
        project_id=project.id,
        title="Add graph-first search",
        issue_type="task",
        epic_key=epic.source_key,
        labels=["agent-work"],
    )
    assert epic.source_type == "platform"
    assert epic.sync_config_id is None
    assert epic.sync_state == "platform_native"
    prefix, epic_n = epic.source_key.rsplit("-", 1)
    task_prefix, task_n = task.source_key.rsplit("-", 1)
    assert prefix == task_prefix
    assert int(task_n) == int(epic_n) + 1
    assert task.epic_key == epic.source_key
    audit = (
        await db.execute(
            select(AuditLog).where(
                AuditLog.action == "secure_work.platform_item_created",
                AuditLog.resource_id == task.id,
            )
        )
    ).scalar_one()
    assert audit.details["epic_key"] == epic.source_key


@pytest.mark.asyncio
async def test_create_rejects_unknown_epic_and_bad_type(db):
    admin, project = await _admin_and_project(db)
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc:
        await create_platform_work_item(
            db, current_user=admin, project_id=project.id, title="x", epic_key="NOPE-1"
        )
    assert exc.value.status_code == 422
    with pytest.raises(HTTPException) as exc:
        await create_platform_work_item(
            db, current_user=admin, project_id=project.id, title="x", issue_type="saga"
        )
    assert exc.value.status_code == 422


@pytest.mark.asyncio
async def test_a_story_is_a_platform_type_under_its_epic(db):
    admin, project = await _admin_and_project(db)
    epic = await create_platform_work_item(db, current_user=admin, project_id=project.id, title="Coffee",
                                           issue_type="epic")
    story = await create_platform_work_item(db, current_user=admin, project_id=project.id, title="S1 navigation",
                                            issue_type="Story", epic_key=epic.source_key)
    assert story.issue_type == "story" and story.epic_key == epic.source_key


@pytest.mark.asyncio
async def test_platform_item_never_reaches_jira_write_back(db):
    admin, project = await _admin_and_project(db)
    item = await create_platform_work_item(
        db, current_user=admin, project_id=project.id, title="local only"
    )

    class _Workflow:
        sync_policy_json = {"sync_mode": "execute"}

    result = await execute_jira_state_sync(
        db,
        item=item,
        workflow=_Workflow(),
        preview={"jira_sync_preview": {"sync_back": True, "transition": "Start Progress"}},
    )
    assert result is None  # execute-mode workflow, but the item is not a Jira item


@pytest.mark.asyncio
async def test_handover_context_includes_notes_sessions_and_digest(db):
    admin, project = await _admin_and_project(db)
    epic = await create_platform_work_item(
        db, current_user=admin, project_id=project.id, title="Epic", issue_type="epic"
    )
    task = await create_platform_work_item(
        db,
        current_user=admin,
        project_id=project.id,
        title="Task under epic",
        epic_key=epic.source_key,
        description="Do the thing",
    )
    await add_work_item_note(db, item=task, note="Worker 1: half done, tests missing", current_user=admin)

    client_session_id = f"claude-code-{uuid.uuid4().hex[:8]}"
    # session_ingest keeps the digest as the shadow session's messages and the summary in its metadata.
    session = Session(
        id=str(uuid.uuid4()),
        user_id=admin.id,
        project_id=project.id,
        agent_type="external_agent",
        status="completed",
        metadata_={"client_session_id": client_session_id, "summary": "Implemented half of the thing."},
    )
    db.add(session)
    await db.flush()
    started = utc_now()
    db.add_all(
        [
            Message(session_id=session.id, role="user", content="do the thing", created_at=started),
            Message(
                session_id=session.id,
                role="assistant",
                content="Implemented parser, validator still open.",
                created_at=started + timedelta(seconds=1),
            ),
        ]
    )
    await db.flush()

    link = await link_session_to_work_item(
        db, item=task, client_session_id=client_session_id, current_user=admin
    )
    assert link["platform_session_found"] is True
    refreshed = await db.get(Session, session.id)
    assert task.source_key in refreshed.metadata_["work_item_keys"]

    context = await build_work_item_context(db, item=task)
    assert context["work_item"]["source_key"] == task.source_key
    assert context["notes"][0]["note"].startswith("Worker 1")
    linked = context["linked_sessions"][0]
    assert linked["client_session_id"] == client_session_id
    assert "validator still open" in linked["digest_tail"]
    assert context["unknowns"] == []

    epic_context = await build_work_item_context(db, item=epic)
    assert [child["source_key"] for child in epic_context["children"]] == [task.source_key]
