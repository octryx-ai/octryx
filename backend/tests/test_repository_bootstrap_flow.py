import json
import uuid

import pytest
from sqlalchemy import select

import app.agent.engine as engine_module
from app.agent.engine import run_agent
from app.models import Project, Session, User
from tests.run_capability_support import DECLARED_CHANGE_RUN


@pytest.mark.asyncio
async def test_run_agent_bootstraps_git_repository_before_writing(db, monkeypatch, tmp_path):
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    project = Project(
        id=str(uuid.uuid4()),
        name="repo-bootstrap-project",
        description="Repository bootstrap E2E test",
        is_active=True,
        config={
            "repository_bootstrap": {
                "enabled": True,
                "provider": "local",
                "auto_bootstrap_on_session_start": False,
                "default_branch": "main",
                "default_repo_name": "repo-bootstrap-project",
            }
        },
    )
    session = Session(
        id=str(uuid.uuid4()),
        user_id=admin.id,
        project_id=project.id,
        agent_type="change",
        status="running",
        metadata_={**DECLARED_CHANGE_RUN, "workspace_root": str(tmp_path)},
    )
    db.add(project)
    db.add(session)
    await db.commit()

    prompt = "Initialisiere das Coding-Workspace sauber und erstelle src/hello.py mit einer hello_world Funktion."
    response_queue = [
        (
            {
                "content": "",
                "tool_calls": [
                    {
                        "id": "call-write-file",
                        "function": {
                            "name": "write_workspace_file",
                            "arguments": json.dumps(
                                {
                                    "path": "src/hello.py",
                                    "content": "def hello_world():\n    return 'hello world'\n",
                                }
                            ),
                        },
                    }
                ],
                "model": "test-model",
                "usage": {"prompt_tokens": 20, "completion_tokens": 10, "total_tokens": 30},
            },
            {"provider_name": "test-provider", "model": "test-model"},
        ),
        (
            {
                "content": "Workspace initialisiert, Datei erstellt und bereit fuer weitere Coding-Schritte.",
                "tool_calls": None,
                "model": "test-model",
                "usage": {"prompt_tokens": 12, "completion_tokens": 14, "total_tokens": 26},
            },
            {"provider_name": "test-provider", "model": "test-model"},
        ),
    ]

    async def fake_resolve_control_plane_runtimes(_db, runtime_target_id=None):
        return [{"provider_name": "test-provider", "model": "test-model"}]

    async def fake_chat_with_runtime_fallback(*, runtimes, messages, tools, max_tokens=4096, reasoning_effort=None):
        return response_queue.pop(0)

    monkeypatch.setattr(engine_module, "resolve_control_plane_runtimes", fake_resolve_control_plane_runtimes)
    monkeypatch.setattr(engine_module, "_chat_with_runtime_fallback", fake_chat_with_runtime_fallback)

    events = []
    async for event in run_agent(
        session_id=session.id,
        user_message=prompt,
        user_id=admin.id,
        project_id=project.id,
        agent_type="change",
        db=db,
    ):
        events.append(event)

    assert (tmp_path / ".git").exists()
    assert (tmp_path / "README.md").exists()
    assert (tmp_path / ".gitignore").exists()
    assert (tmp_path / "src" / "hello.py").read_text(
        encoding="utf-8"
    ) == "def hello_world():\n    return 'hello world'\n"
    assert any(event.role == "tool" for event in events)
    assert any("bereit fuer weitere Coding-Schritte" in (event.content or "") for event in events)
