"""Tests for prepare_agent_run context injection, repo microagents, and semantic pruning."""

import asyncio
import uuid
from pathlib import Path

import pytest
from sqlalchemy import select

from app.agent.core.context.run_context import prepare_agent_run
from app.models import Project, Session, User
from tests.run_capability_support import DECLARED_CHANGE_RUN
from tests.skill_catalog.support import publish_chat_skill


@pytest.mark.asyncio
async def test_prepare_agent_run_guides_skill_search_without_auto_injecting_skill_content(db, tmp_path: Path):
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    project = (await db.execute(select(Project).where(Project.name == "acme-orders"))).scalar_one()
    session = Session(id=str(uuid.uuid4()), user_id=admin.id, project_id=project.id, agent_type="change", metadata_=dict(DECLARED_CHANGE_RUN))
    await publish_chat_skill(db, "sensitive-skill", approver_id=admin.id, description="Sensitive summary",
                             category="change", body="SECRET FULL SKILL CONTENT", allowed_roles=("admin",))
    db.add(session)
    await db.commit()

    prepared = await prepare_agent_run(
        db=db,
        session_id=session.id,
        user_message="Implement a small change using the right operating method",
        user_id=admin.id,
        project_id=project.id,
        agent_type="change",
        runtime_target_id=None,
        thinking_level="light",
        agent_definition=None,
        parent_session_id=None,
        sub_agent_depth=0,
        workspace_root=str(tmp_path),
        resolve_model_context_cap=lambda *args, **kwargs: asyncio.sleep(0, result=None),
        resolve_control_plane_runtimes_func=lambda *args, **kwargs: asyncio.sleep(0, result=[]),
        filter_tool_definitions=lambda definitions, _allow: definitions,
        exclude_tool_definitions=lambda definitions, _blocked: definitions,
        trim_messages_to_budget=lambda messages, _budget: messages,
    )

    assert "skill_search" in prepared.system_prompt
    assert "SECRET FULL SKILL CONTENT" not in prepared.system_prompt
    tool_names = {definition["function"]["name"] for definition in prepared.tool_definitions}
    assert {"skill_search", "skill_get"} <= tool_names


@pytest.mark.asyncio
async def test_prepare_agent_run_grounds_only_from_explicit_settings(db, tmp_path: Path):
    """"What changed in the latest Jira release?" gets the contract from the Workspace setting, not its words."""
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()

    async def _prepare(config: dict) -> object:
        project = Project(id=str(uuid.uuid4()), name=f"empty-risk-{uuid.uuid4().hex[:6]}", is_active=True, config=config)
        session = Session(
            id=str(uuid.uuid4()), user_id=admin.id, project_id=project.id, agent_type="diagnosis", metadata_={}
        )
        db.add_all([project, session])
        await db.commit()
        return await prepare_agent_run(
            db=db,
            session_id=session.id,
            user_message="What changed in the latest Jira release?",
            user_id=admin.id,
            project_id=project.id,
            agent_type="diagnosis",
            runtime_target_id=None,
            thinking_level="light",
            agent_definition=None,
            parent_session_id=None,
            sub_agent_depth=0,
            workspace_root=str(tmp_path),
            resolve_model_context_cap=lambda *args, **kwargs: asyncio.sleep(0, result=None),
            resolve_control_plane_runtimes_func=lambda *args, **kwargs: asyncio.sleep(0, result=[]),
            filter_tool_definitions=lambda definitions, _allow: definitions,
            exclude_tool_definitions=lambda definitions, _blocked: definitions,
            trim_messages_to_budget=lambda messages, _budget: messages,
        )

    ungoverned = await _prepare({})
    assert "Evidence-Grounded Answer Contract" not in ungoverned.system_prompt
    assert "evidence_grounding_policy" not in ungoverned.session_metadata

    prepared = await _prepare({"evidence_grounding_policy": {"mode": "required"}})
    assert "Evidence-Grounded Answer Contract" in prepared.system_prompt
    assert "no retrieved evidence has been injected" in prepared.system_prompt
    assert "do not fill the gap with plausible invented details" in prepared.system_prompt
    grounding = prepared.session_metadata["evidence_grounding_policy"]
    assert grounding["applies"] is True
    assert grounding["triggers"] == ["workspace_setting_required"]
    assert grounding["evidence_available"] is False
