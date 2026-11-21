"""The coding loop stops on repeated no-execution or intent-only responses and suppresses a preamble next to a tool call."""

import json
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import select

import app.agent.engine as engine_module
from app.agent.engine import (
    run_agent,
)
from app.models import Message, Project, Session, TurnTrace, User
from app.services.workflow_routing.workflow_selection import ROUTING_RESOLUTION_KEY
from app.services.workflow_runs.binding import phase_resolution
from app.web import _context as web_context
from tests.run_capability_support import DECLARED_CHANGE_RUN, UNDECLARED_READ_ONLY_RUN

SEEDS = Path(__file__).resolve().parents[1] / "app/services/workflow_runs/seeds/phased_workflows.json"


def _tdd_phase_resolution() -> dict:
    """The resolution of the bug-fix workflow run's coding phase (``coding_change_tdd``)."""
    seed = next(item for item in json.loads(SEEDS.read_text()) if item["key"] == "bug-fix-reproduction")
    node = next(node for node in seed["definition"]["nodes"] if node.get("id") == "fix")
    run = SimpleNamespace(id="run-tdd", workflow_key=seed["key"], workflow_kind="phased", node_state={})
    return phase_resolution(run=run, node_id="fix", definition=node["config"])


def _no_execution_responses() -> list[dict]:
    return [
        {
            "content": "I am going to update the divide function in calculator.py and then write tests.",
            "tool_calls": None,
            "model": "Claude Haiku 4.5",
            "usage": {"prompt_tokens": 10, "completion_tokens": 4, "total_tokens": 14},
        },
        {
            "content": "I am going to add the tests and run the verification.",
            "tool_calls": None,
            "model": "Claude Haiku 4.5",
            "usage": {"prompt_tokens": 11, "completion_tokens": 4, "total_tokens": 15},
        },
    ]


def _write_then_intent_only_responses() -> list[dict]:
    return [
        {
            "content": "",
            "tool_calls": [
                {
                    "id": "tool-write",
                    "function": {
                        "name": "write_workspace_file",
                        "arguments": json.dumps(
                            {
                                "path": "calculator.py",
                                "content": "def divide(a, b):\n    if b == 0:\n        raise ValueError('division by zero')\n    return a / b\n",
                            }
                        ),
                    },
                }
            ],
            "model": "Claude Haiku 4.5",
            "usage": {"prompt_tokens": 12, "completion_tokens": 6, "total_tokens": 18},
        },
        {
            "content": "Now I'll create the pytest tests and then run the verification.",
            "tool_calls": None,
            "model": "Claude Haiku 4.5",
            "usage": {"prompt_tokens": 10, "completion_tokens": 4, "total_tokens": 14},
        },
        {
            "content": "Next I'll run the tests and summarize the result.",
            "tool_calls": None,
            "model": "Claude Haiku 4.5",
            "usage": {"prompt_tokens": 10, "completion_tokens": 4, "total_tokens": 14},
        },
    ]


def _preamble_with_tool_call_responses() -> list[dict]:
    return [
        {
            "content": "✅ calculator.py created. Now I'll create the pytest tests.",
            "tool_calls": [
                {
                    "id": "tool-list",
                    "function": {
                        "name": "list_workspace_directory",
                        "arguments": json.dumps({"path": "."}),
                    },
                }
            ],
            "model": "Claude Haiku 4.5",
            "usage": {"prompt_tokens": 12, "completion_tokens": 6, "total_tokens": 18},
        },
        {
            "content": "Done.",
            "tool_calls": None,
            "model": "Claude Haiku 4.5",
            "usage": {"prompt_tokens": 8, "completion_tokens": 2, "total_tokens": 10},
        },
    ]


async def _admin_and_project(db):
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    project = (await db.execute(select(Project).where(Project.name == "acme-orders"))).scalar_one()
    return admin, project


async def _seed_coding_session(db, admin, project, metadata: dict) -> Session:
    session = Session(
        id=str(uuid.uuid4()),
        user_id=admin.id,
        project_id=project.id,
        agent_type="coding",
        status="running",
        metadata_=metadata,
    )
    db.add(session)
    await db.commit()
    return session


def _stub_runtime_responses(monkeypatch, response_queue: list[dict]) -> None:
    async def fake_resolve_control_plane_runtimes(_db, runtime_target_id=None):
        return [{"provider_name": "copilot", "model": "claude-haiku-4.5"}]

    async def fake_chat_with_runtime_fallback(*, runtimes, messages, tools, max_tokens=4096, reasoning_effort=None):
        return response_queue.pop(0), runtimes[0]

    monkeypatch.setattr(engine_module, "resolve_control_plane_runtimes", fake_resolve_control_plane_runtimes)
    monkeypatch.setattr(engine_module, "_chat_with_runtime_fallback", fake_chat_with_runtime_fallback)


async def _run_coding_agent(db, session, admin, project, user_message: str) -> list:
    events = []
    async for event in run_agent(
        session_id=session.id,
        user_message=user_message,
        user_id=admin.id,
        project_id=project.id,
        agent_type="coding",
        db=db,
    ):
        events.append(event)
    return events


async def _session_turn_traces(db, session_id: str) -> list[TurnTrace]:
    return (
        (
            await db.execute(
                select(TurnTrace).where(TurnTrace.session_id == session_id).order_by(TurnTrace.created_at.asc())
            )
        )
        .scalars()
        .all()
    )


@pytest.mark.asyncio
async def test_run_agent_stops_on_repeated_coding_no_execution_responses(db, monkeypatch, tmp_path):
    admin, project = await _admin_and_project(db)
    workspace_root = tmp_path / "coding-no-execution"
    workspace_root.mkdir(parents=True, exist_ok=True)
    # The run indexes the project workspace; point it at this fixture, not the platform's own checkout (8450 files).
    monkeypatch.setattr(web_context, "WORKSPACE_ROOT", workspace_root.resolve())
    (workspace_root / "calculator.py").write_text("def divide(a, b):\n    return a / b\n", encoding="utf-8")
    session = await _seed_coding_session(
        db, admin, project, {**DECLARED_CHANGE_RUN, "workspace_root": str(workspace_root)}
    )

    response_queue = _no_execution_responses()
    _stub_runtime_responses(monkeypatch, response_queue)

    events = await _run_coding_agent(
        db,
        session,
        admin,
        project,
        "Please implement divide in calculator.py with division-by-zero handling and run the verification.",
    )

    assert events
    assert "kept describing the next coding step instead of executing it" in events[-1].content

    traces = await _session_turn_traces(db, session.id)
    assert any((trace.raw_output or {}).get("suppressed_for_coding_intent_only") for trace in traces)
    assert any((trace.raw_output or {}).get("stalled_on_coding_intent_only") for trace in traces)


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_run_agent_stops_on_repeated_coding_intent_only_responses_after_write(db, monkeypatch, tmp_path):
    admin, project = await _admin_and_project(db)
    workspace_root = tmp_path / "coding-intent-only"
    workspace_root.mkdir(parents=True, exist_ok=True)
    (workspace_root / "calculator.py").write_text("def divide(a, b):\n    return a / b\n", encoding="utf-8")
    user_message = (
        "Please implement divide in calculator.py with division-by-zero handling, "
        "create pytest tests and run the verification."
    )
    # The TDD contract comes only from the workflow run's coding phase, never from the wording.
    tdd_resolution = _tdd_phase_resolution()
    session = await _seed_coding_session(
        db,
        admin,
        project,
        {
            **DECLARED_CHANGE_RUN,
            "workspace_root": str(workspace_root),
            ROUTING_RESOLUTION_KEY: tdd_resolution,
        },
    )

    response_queue = _write_then_intent_only_responses()
    _stub_runtime_responses(monkeypatch, response_queue)

    events = await _run_coding_agent(db, session, admin, project, user_message)

    assert events
    assert "kept producing text without using its required tools" in events[-1].content

    traces = await _session_turn_traces(db, session.id)
    raw_outputs = [trace.raw_output or {} for trace in traces]
    assert any(raw.get("suppressed_for_incomplete_tdd_cycle") for raw in raw_outputs)
    assert any(
        raw.get("stalled_final_step")
        or raw.get("stalled_on_transitional_loop")
        or raw.get("stalled_on_followup_no_tool_loop")
        for raw in raw_outputs
    )


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_run_agent_suppresses_coding_preamble_when_tool_call_is_present(db, monkeypatch, tmp_path):
    admin, project = await _admin_and_project(db)
    workspace_root = tmp_path / "coding-tool-preamble"
    workspace_root.mkdir(parents=True, exist_ok=True)
    (workspace_root / "calculator.py").write_text("def divide(a, b):\n    return a / b\n", encoding="utf-8")
    session = await _seed_coding_session(
        db, admin, project, {**UNDECLARED_READ_ONLY_RUN, "workspace_root": str(workspace_root)}
    )

    response_queue = _preamble_with_tool_call_responses()
    _stub_runtime_responses(monkeypatch, response_queue)

    events = await _run_coding_agent(
        db,
        session,
        admin,
        project,
        "Please implement divide in calculator.py with division-by-zero handling, create pytest tests and run the verification.",
    )

    assert events
    assistant_messages = (
        (
            await db.execute(
                select(Message)
                .where(Message.session_id == session.id, Message.role == "assistant")
                .order_by(Message.created_at.asc())
            )
        )
        .scalars()
        .all()
    )
    assert all(
        "Now I'll create the pytest tests" not in str(message.content or "") for message in assistant_messages
    )
    assert any(message.tool_calls for message in assistant_messages)
