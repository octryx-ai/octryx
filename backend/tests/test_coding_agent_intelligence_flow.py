"""The coding agent uses code intelligence before it writes."""

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

_RUNTIME = {"provider_name": "test-provider", "model": "test-model"}
_USAGE = {"prompt_tokens": 10, "completion_tokens": 10, "total_tokens": 20}


def _tool_turn(call_id, tool_name, arguments):
    return (
        {
            "content": "",
            "tool_calls": [{"id": call_id, "function": {"name": tool_name, "arguments": json.dumps(arguments)}}],
            "model": "test-model",
            "usage": dict(_USAGE),
        },
        dict(_RUNTIME),
    )


def _scripted_responses():
    """Search, find the definition, write the test, then finish."""
    return [
        _tool_turn("call-code-search", "code_search", {"query": "helper", "cwd": "."}),
        _tool_turn("call-symbol-definition", "code_symbol_definition", {"symbol": "helper", "cwd": "."}),
        _tool_turn(
            "call-write-file",
            "write_workspace_file",
            {
                "path": "tests/test_helper.py",
                "content": "from src.app import helper\n\n\ndef test_helper_returns_hello_world():\n    assert helper() == 'hello world'\n",
            },
        ),
        (
            {
                "content": "Repository analysiert, Testdatei erstellt und Git-Repository initialisiert.",
                "tool_calls": None,
                "model": "test-model",
                "usage": dict(_USAGE),
            },
            dict(_RUNTIME),
        ),
    ]


def _prepare_workspace(tmp_path, monkeypatch):
    workspace = tmp_path / "coding-agent-workspace"
    if workspace.exists():
        shutil.rmtree(workspace)
    workspace.mkdir(parents=True, exist_ok=True)
    _write_fixture(workspace)
    # The run indexes the project workspace; point it at this fixture, not the platform's own large checkout.
    monkeypatch.setattr(web_context, "WORKSPACE_ROOT", workspace.resolve())
    return workspace


async def _seed_project_session(db, admin, workspace):
    project = Project(
        id=str(uuid.uuid4()),
        name="coding-agent-project",
        description="coding agent flow",
        is_active=True,
        config={
            "repository_bootstrap": {
                "enabled": True,
                "provider": "local",
                "auto_bootstrap_on_session_start": False,
                "default_branch": "main",
                "default_repo_name": "coding-agent-project",
            }
        },
    )
    session = Session(
        id=str(uuid.uuid4()),
        user_id=admin.id,
        project_id=project.id,
        agent_type="change",
        status="running",
        metadata_={**DECLARED_CHANGE_RUN, "workspace_root": str(workspace)},
    )
    db.add(project)
    db.add(session)
    await db.commit()
    return project, session


async def _run_with_scripted_model(db, admin, project, session, responses):
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
            user_message="Analysiere helper, finde den Definitionsort und erstelle danach einen Test dafuer.",
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


async def _tool_call_names(db, session):
    return (
        (
            await db.execute(
                select(ToolCall.tool_name).where(ToolCall.session_id == session.id).order_by(ToolCall.created_at.asc())
            )
        )
        .scalars()
        .all()
    )


@pytest.mark.asyncio
async def test_coding_agent_uses_code_intelligence_before_write(tmp_path: Path, monkeypatch):
    engine = _create_test_engine(tmp_path, "coding-agent.db")
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)

    async with session_factory() as db:
        await _seed(db)
        admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
        workspace = _prepare_workspace(tmp_path, monkeypatch)
        project, session = await _seed_project_session(db, admin, workspace)
        events = await _run_with_scripted_model(db, admin, project, session, _scripted_responses())

        assert (workspace / ".git").exists()
        assert (workspace / "tests" / "test_helper.py").exists()
        tool_calls = await _tool_call_names(db, session)
        assert "code_search" in tool_calls
        assert "code_symbol_definition" in tool_calls
        assert "write_workspace_file" in tool_calls
        assert "run_test_suite" in tool_calls
        assert _has_verified_coding_completion(events)

    await engine.dispose()
