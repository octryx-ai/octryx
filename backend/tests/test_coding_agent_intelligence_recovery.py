"""The coding agent prefers repository preflight over a blind write recovery."""

from __future__ import annotations

import json
import shutil
import uuid
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

import app.agent.engine as engine_module
from app.agent.engine import run_agent
from app.db import Base
from app.models import Project, Session, ToolCall, User
from app.web import _context as web_context
from tests.coding_agent_intelligence_flow_support import (  # noqa: F401
    _create_test_engine,
    _has_verified_coding_completion,
    _seed,
    _server_pipeline,
    _write_fixture,
)
from tests.run_capability_support import DECLARED_CHANGE_RUN

_HELPER_TEST_SOURCE = "from src.app import helper\n\n\ndef test_helper_returns_hello_world():\n    assert helper() == 'hello world'\n"


def _prepare_workspace(tmp_path: Path, monkeypatch) -> Path:
    workspace = tmp_path / "coding-agent-guard-workspace"
    if workspace.exists():
        shutil.rmtree(workspace)
    workspace.mkdir(parents=True, exist_ok=True)
    _write_fixture(workspace)
    # The run indexes the project workspace; point it at this fixture, not the platform's own large checkout.
    monkeypatch.setattr(web_context, "WORKSPACE_ROOT", workspace.resolve())
    return workspace


def _guard_project_and_session(admin_id: str, workspace: Path) -> tuple[Project, Session]:
    project = Project(
        id=str(uuid.uuid4()),
        name="coding-agent-guard-project",
        description="coding agent guard flow",
        is_active=True,
        config={
            "repository_bootstrap": {
                "enabled": True,
                "provider": "local",
                "auto_bootstrap_on_session_start": False,
                "default_branch": "main",
                "default_repo_name": "coding-agent-guard-project",
            }
        },
    )
    session = Session(
        id=str(uuid.uuid4()),
        user_id=admin_id,
        project_id=project.id,
        agent_type="change",
        status="running",
        metadata_={**DECLARED_CHANGE_RUN, "workspace_root": str(workspace)},
    )
    return project, session


def _blind_write_responses() -> list[tuple[dict, dict]]:
    """The model writes the test file straight away, then reports completion."""
    return [
        (
            {
                "content": "",
                "tool_calls": [
                    {
                        "id": "call-write-after-analysis",
                        "function": {
                            "name": "write_workspace_file",
                            "arguments": json.dumps(
                                {
                                    "path": "tests/test_helper.py",
                                    "content": _HELPER_TEST_SOURCE,
                                }
                            ),
                        },
                    }
                ],
                "model": "test-model",
                "usage": {"prompt_tokens": 10, "completion_tokens": 10, "total_tokens": 20},
            },
            {"provider_name": "test-provider", "model": "test-model"},
        ),
        (
            {
                "content": "Repository analysiert, Guard beachtet und Testdatei erstellt.",
                "tool_calls": None,
                "model": "test-model",
                "usage": {"prompt_tokens": 10, "completion_tokens": 10, "total_tokens": 20},
            },
            {"provider_name": "test-provider", "model": "test-model"},
        ),
    ]


async def _run_with_scripted_llm(db, session, admin, project, responses) -> list[tuple[str, str]]:
    original_resolve = engine_module.resolve_control_plane_runtimes
    original_chat = engine_module._chat_with_runtime_fallback

    async def fake_resolve_control_plane_runtimes(_db, runtime_target_id=None):
        return [{"provider_name": "test-provider", "model": "test-model"}]

    async def fake_chat_with_runtime_fallback(*, runtimes, messages, tools, max_tokens=4096, reasoning_effort=None):
        return responses.pop(0)

    engine_module.resolve_control_plane_runtimes = fake_resolve_control_plane_runtimes
    engine_module._chat_with_runtime_fallback = fake_chat_with_runtime_fallback
    try:
        events = []
        async for event in run_agent(
            session_id=session.id,
            user_message="Erstelle einen Test fuer helper und schreibe nicht blind in den Code.",
            user_id=admin.id,
            project_id=project.id,
            agent_type="change",
            db=db,
        ):
            events.append((event.role, event.content or ""))
    finally:
        engine_module.resolve_control_plane_runtimes = original_resolve
        engine_module._chat_with_runtime_fallback = original_chat
    return events


@pytest.mark.asyncio
async def test_coding_agent_prefers_preflight_over_blind_write_recovery(tmp_path: Path, monkeypatch):
    engine = _create_test_engine(tmp_path, "coding-agent-guard.db")
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)

    async with session_factory() as db:
        await _seed(db)
        admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()

        workspace = _prepare_workspace(tmp_path, monkeypatch)

        project, session = _guard_project_and_session(admin.id, workspace)
        db.add(project)
        db.add(session)
        await db.commit()

        responses = _blind_write_responses()

        events = await _run_with_scripted_llm(db, session, admin, project, responses)

        assert (workspace / ".git").exists()
        assert (workspace / "tests" / "test_helper.py").exists()
        tool_calls = (
            (
                await db.execute(
                    select(ToolCall).where(ToolCall.session_id == session.id).order_by(ToolCall.created_at.asc())
                )
            )
            .scalars()
            .all()
        )
        assert [item.tool_name for item in tool_calls] == [
            "bootstrap_workspace_repository",
            "analyze_workspace_repository",
            "code_search",
            "write_workspace_file",
            "run_test_suite",
        ]
        assert tool_calls[0].status == "success"
        assert _has_verified_coding_completion(events)

    await engine.dispose()
