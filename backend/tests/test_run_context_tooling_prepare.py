"""prepare_agent_run uses the extracted tool definition builder, the resolved engineering repository and the secure-work repo allowlist."""

from __future__ import annotations

import asyncio
import uuid
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import select

from app.agent.core.context.run_context import prepare_agent_run
from app.models import Session, User
from app.services.workflow_routing.workflow_selection import ROUTING_RESOLUTION_KEY
from tests.run_context_tooling_support import _db_routing_resolution, _tool


@pytest.mark.asyncio
async def test_prepare_agent_run_uses_extracted_tool_definition_builder(db, tmp_path: Path, monkeypatch) -> None:
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    routing_resolution = _db_routing_resolution(allowlist=["aws_topology_snapshot"])
    session = Session(
        id=str(uuid.uuid4()),
        user_id=admin.id,
        agent_type="diagnosis",
        metadata_={ROUTING_RESOLUTION_KEY: routing_resolution},
    )
    db.add(session)
    await db.commit()

    captured: dict[str, Any] = {}

    async def fake_tool_builder(**kwargs):
        captured["include_tools"] = kwargs["include_tools"]
        captured["tool_allowlist"] = list(kwargs["tool_allowlist"])
        captured["blocked_tools"] = list(kwargs["blocked_tools"])
        captured["tool_context_session_id"] = kwargs["tool_context"].session_id
        captured["workflow_routing_policy_resolution"] = kwargs["workflow_routing_policy_resolution"]
        return [_tool("list_failed_pods")]

    monkeypatch.setattr(
        "app.agent.core.context.run_context_tool_offer.build_run_context_tool_definitions",
        fake_tool_builder,
    )

    prepared = await prepare_agent_run(
        db=db,
        session_id=session.id,
        user_message="Why is the payment-service pod in CrashLoopBackOff on kubernetes?",
        user_id=admin.id,
        project_id=None,
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

    assert captured["tool_context_session_id"] == session.id
    assert captured["workflow_routing_policy_resolution"] == routing_resolution
    assert captured["include_tools"] is True
    # The selected definition's allowlist governs the surface.
    assert "aws_topology_snapshot" in captured["tool_allowlist"]
    assert prepared.context_plan.tool_surface_source == "selected_definition"
    assert isinstance(captured["blocked_tools"], list)
    assert [definition["function"]["name"] for definition in prepared.tool_definitions] == ["list_failed_pods"]


@pytest.mark.asyncio
async def test_prepare_agent_run_uses_resolved_engineering_repository_for_tools(
    db,
    tmp_path: Path,
    monkeypatch,
) -> None:
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    session_workspace = tmp_path / "session-workspace"
    session_workspace.mkdir()
    repo_root = tmp_path / "acme-orders-access-proxy"
    repo_root.mkdir()
    session = Session(id=str(uuid.uuid4()), user_id=admin.id, agent_type="diagnosis", metadata_={})
    db.add(session)
    await db.commit()

    async def fake_runtime_prompt(**_kwargs):
        return (
            "Engineering Knowledge Runtime Context",
            {
                "prompt_contract": {"intent": "coding_migration"},
                "repository": {"id": "repo-1", "name": "acme-orders-access-proxy", "repo_root": str(repo_root)},
                "engineering_knowledge_pack": {"version_id": "version-1", "quality_status": "passed"},
                "blockers": [],
            },
        )

    async def fake_load_repo_context_prompts(**kwargs):
        captured["repo_context_workspace_root"] = kwargs["workspace_root"]
        return "", ""

    captured: dict[str, Any] = {}

    async def fake_tool_builder(**kwargs):
        tool_context = kwargs["tool_context"]
        captured["tool_context_workspace_root"] = tool_context.workspace_root
        captured["project_config_workspace_root"] = tool_context.project_config["workspace_root"]
        captured["resolved_repository_root"] = tool_context.project_config["resolved_repository_root"]
        captured["session_workspace_root"] = tool_context.project_config["session_workspace_root"]
        return [_tool("code_search")]

    monkeypatch.setattr(
        "app.agent.core.context.run_context_knowledge.resolve_engineering_knowledge_runtime_prompt",
        fake_runtime_prompt,
    )
    monkeypatch.setattr(
        "app.agent.core.context.run_context_knowledge.load_repo_context_prompts",
        fake_load_repo_context_prompts,
    )
    monkeypatch.setattr(
        "app.agent.core.context.run_context_tool_offer.build_run_context_tool_definitions",
        fake_tool_builder,
    )

    prepared = await prepare_agent_run(
        db=db,
        session_id=session.id,
        user_message="Migriere acme-orders-access-proxy zu Java 25 und Spring Boot 4.0.3.",
        user_id=admin.id,
        project_id=None,
        agent_type="diagnosis",
        runtime_target_id=None,
        thinking_level="light",
        agent_definition=None,
        parent_session_id=None,
        sub_agent_depth=0,
        workspace_root=str(session_workspace),
        resolve_model_context_cap=lambda *args, **kwargs: asyncio.sleep(0, result=None),
        resolve_control_plane_runtimes_func=lambda *args, **kwargs: asyncio.sleep(0, result=[]),
        filter_tool_definitions=lambda definitions, _allow: definitions,
        exclude_tool_definitions=lambda definitions, _blocked: definitions,
        trim_messages_to_budget=lambda messages, _budget: messages,
    )

    assert captured["tool_context_workspace_root"] == str(repo_root.resolve())
    assert captured["repo_context_workspace_root"] == str(repo_root.resolve())
    assert captured["project_config_workspace_root"] == str(repo_root.resolve())
    assert captured["resolved_repository_root"] == str(repo_root.resolve())
    assert captured["session_workspace_root"] == str(session_workspace.resolve())
    assert prepared.tool_context.workspace_root == str(repo_root.resolve())


@pytest.mark.asyncio
async def test_prepare_agent_run_exposes_secure_work_repo_allowlist(db, tmp_path: Path, monkeypatch) -> None:
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    session_workspace = tmp_path / "session-workspace"
    coding_workspace = session_workspace / "coding-runs" / "ACME-615" / "run-1" / "repo"
    coding_workspace.mkdir(parents=True)
    session = Session(
        id=str(uuid.uuid4()),
        user_id=admin.id,
        agent_type="coding",
        metadata_={
            "secure_work_execution_workspace": {"primary_workspace_root": str(coding_workspace)},
            "coding_workspace_records": [
                {
                    "project_key": "SHOP",
                    "repository_slug": "aws-shop-infrastructure",
                    "repository_name": "AWS Shop Infrastructure",
                }
            ],
        },
    )
    db.add(session)
    await db.commit()
    captured: dict[str, Any] = {}

    async def fake_tool_builder(**kwargs):
        tool_context = kwargs["tool_context"]
        captured["workspace_root"] = tool_context.workspace_root
        captured["project_config"] = dict(tool_context.project_config)
        return [_tool("prepare_bitbucket_repository")]

    monkeypatch.setattr(
        "app.agent.core.context.run_context_tool_offer.build_run_context_tool_definitions",
        fake_tool_builder,
    )

    await prepare_agent_run(
        db=db,
        session_id=session.id,
        user_message="Execute the approved Work Plan.",
        user_id=admin.id,
        project_id=None,
        agent_type="coding",
        runtime_target_id=None,
        thinking_level="light",
        agent_definition=None,
        parent_session_id=None,
        sub_agent_depth=0,
        workspace_root=str(session_workspace),
        resolve_model_context_cap=lambda *args, **kwargs: asyncio.sleep(0, result=None),
        resolve_control_plane_runtimes_func=lambda *args, **kwargs: asyncio.sleep(0, result=[]),
        filter_tool_definitions=lambda definitions, _allow: definitions,
        exclude_tool_definitions=lambda definitions, _blocked: definitions,
        trim_messages_to_budget=lambda messages, _budget: messages,
    )

    assert captured["workspace_root"] == str(coding_workspace.resolve())
    assert captured["project_config"]["managed_repo_root"] == "var/repos/bitbucket"
    assert captured["project_config"]["bitbucket_allowed_repos"] == [
        {
            "project_key": "SHOP",
            "repo_slug": "aws-shop-infrastructure",
            "enabled": True,
            "label": "AWS Shop Infrastructure",
            "source": "secure_work_coding_workspace",
        }
    ]
