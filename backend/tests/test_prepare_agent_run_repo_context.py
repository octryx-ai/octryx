"""prepare_agent_run injects only explicitly active or definition-bound repo microagents and repo knowledge."""

import asyncio
import uuid
from pathlib import Path

import pytest
from sqlalchemy import select

from app.agent.core.context.run_context import prepare_agent_run
from app.models import Project, Session, User


@pytest.mark.asyncio
async def test_prepare_agent_run_injects_only_explicitly_active_repo_microagents(db, tmp_path: Path):
    # Always_include loads; a trigger-only entry never loads from prompt words ("deploy", "release").
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    project = Project(
        id=str(uuid.uuid4()),
        name=f"repo-microagents-{uuid.uuid4().hex[:6]}",
        config={
            "managed_repo_root": "var/repos/bitbucket",
            "bitbucket_allowed_repos": [{"project_key": "RIVER", "repo_slug": "service-config", "enabled": True}],
        },
    )
    session = Session(
        id=str(uuid.uuid4()), user_id=admin.id, project_id=project.id, agent_type="diagnosis", metadata_={}
    )
    db.add_all([project, session])
    await db.commit()

    workspace_agent_root = tmp_path / ".agents"
    workspace_agent_root.mkdir(parents=True)
    (workspace_agent_root / "global.md").write_text(
        "---\nname: Global Incident Agent\ntriggers: [incident]\ncapabilities: [diagnosis]\nalways_include: true\n---\nCollect core evidence before narrowing hypotheses.\n",
        encoding="utf-8",
    )

    repo_agent_root = tmp_path / "var" / "repos" / "bitbucket" / "RIVER" / "service-config" / ".agents"
    repo_agent_root.mkdir(parents=True)
    (repo_agent_root / "gitops.md").write_text(
        "---\nname: GitOps Deploy Agent\ndescription: Use branch state carefully\ntriggers: [deploy, release]\ncapabilities: [diagnosis]\npriority: 50\n---\nTreat release/prod branches as deployment truth for service-config.\n",
        encoding="utf-8",
    )

    prepared = await prepare_agent_run(
        db=db,
        session_id=session.id,
        user_message="Investigate the deploy issue in service-config after the release branch changed.",
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

    assert "## Repo Microagents" in prepared.repo_microagents_prompt
    assert "Global Incident Agent" in prepared.repo_microagents_prompt
    assert "GitOps Deploy Agent" not in prepared.repo_microagents_prompt
    assert "release/prod branches as deployment truth" not in prepared.system_prompt


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_prepare_agent_run_injects_only_explicitly_active_repo_knowledge(db, tmp_path: Path):
    # Always_include loads; a trigger-only file never loads from prompt words ("deploy", "release").
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    project = Project(
        id=str(uuid.uuid4()),
        name=f"repo-knowledge-{uuid.uuid4().hex[:6]}",
        config={
            "managed_repo_root": "var/repos/bitbucket",
            "bitbucket_allowed_repos": [{"project_key": "RIVER", "repo_slug": "service-config", "enabled": True}],
        },
    )
    session = Session(
        id=str(uuid.uuid4()), user_id=admin.id, project_id=project.id, agent_type="diagnosis", metadata_={}
    )
    db.add_all([project, session])
    await db.commit()

    workspace_knowledge_root = tmp_path / ".agents" / "knowledge"
    workspace_knowledge_root.mkdir(parents=True)
    (workspace_knowledge_root / "payments.md").write_text(
        "---\ntitle: Payment Runbook\nsummary: Payment incident notes\ntriggers: [payment]\ntags: [runbook]\nalways_include: true\n---\nEscalate to the PSP only after checking their status page and recent deploys.\n",
        encoding="utf-8",
    )

    repo_knowledge_root = tmp_path / "var" / "repos" / "bitbucket" / "RIVER" / "service-config" / ".agents" / "knowledge"
    repo_knowledge_root.mkdir(parents=True)
    (repo_knowledge_root / "gitops.md").write_text(
        "---\ntitle: GitOps Branch Policy\nsummary: Branches define live state\ntriggers: [deploy, release]\ntags: [gitops]\npriority: 50\n---\nRelease and prod branches represent the live deployment state for service-config.\n",
        encoding="utf-8",
    )

    prepared = await prepare_agent_run(
        db=db,
        session_id=session.id,
        user_message="Investigate the deploy issue in service-config after the release branch changed.",
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

    assert "## Repo Knowledge" in prepared.repo_knowledge_prompt
    assert "Payment Runbook" in prepared.repo_knowledge_prompt
    assert "GitOps Branch Policy" not in prepared.repo_knowledge_prompt
    assert "live deployment state for service-config" not in prepared.system_prompt
