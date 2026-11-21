from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.models import Message, Project, Session, TurnTrace, User
from app.services.coding_discipline_service import coding_discipline_stats, recommend_coding_models


async def _seed_session(db, *, name_prefix, description, agent_type, model):
    """A project with one session and an assistant message from ``model``; return (project, session, message)."""
    user = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    project = Project(
        id=str(uuid.uuid4()),
        name=f"{name_prefix}-{uuid.uuid4().hex[:8]}",
        description=description,
        is_active=True,
        config={},
    )
    db.add(project)
    await db.commit()

    session = Session(
        id=str(uuid.uuid4()),
        user_id=user.id,
        project_id=project.id,
        agent_type=agent_type,
        status="active",
        metadata_={},
    )
    message = Message(
        id=str(uuid.uuid4()),
        session_id=session.id,
        role="assistant",
        content="done",
        model=model,
    )
    db.add_all([session, message])
    await db.commit()
    return project, session, message


def _trace(session, message, *, provider, model, context, tools, raw_output, usage):
    return TurnTrace(
        id=str(uuid.uuid4()),
        session_id=session.id,
        message_id=message.id,
        provider=provider,
        model=model,
        context_snapshot_json=context,
        tool_trace_json=tools,
        raw_output=raw_output,
        usage_json=usage,
    )


def _ollama_run(model, duration_ms):
    return {
        "runtime_attempts": [
            {
                "status": "success",
                "provider": "ollama",
                "model": model,
                "duration_ms": duration_ms,
            }
        ]
    }


def _review_and_planning_traces(session, message):
    review_trace = _trace(
        session,
        message,
        provider="ollama",
        model="gemma4:e4b",
        context={
            "subtask_model_role": "self_review",
            "reasoning_stage": "verifier",
        },
        tools=[
            {
                "tool_name": "self_review_workspace_diff",
                "status": "success",
                "duration_ms": 220,
                "result": {"ready_for_pr": True},
            }
        ],
        raw_output=_ollama_run("gemma4:e4b", 900),
        usage={"request_duration_ms": 900},
    )
    planning_trace = _trace(
        session,
        message,
        provider="ollama",
        model="llama3.1:8b",
        context={"reasoning_stage": "planner"},
        tools=[],
        raw_output=_ollama_run("llama3.1:8b", 400),
        usage={"request_duration_ms": 400},
    )
    return [review_trace, planning_trace]


def _repo_and_edit_traces(session, message):
    repo_trace = _trace(
        session,
        message,
        provider="ollama",
        model="llama3.1:8b",
        context={"reasoning_stage": "planner"},
        tools=[
            {"tool_name": "code_search", "status": "success", "duration_ms": 50, "result": {}},
            {"tool_name": "code_symbol_definition", "status": "success", "duration_ms": 60, "result": {}},
        ],
        raw_output=_ollama_run("llama3.1:8b", 450),
        usage={"request_duration_ms": 450},
    )
    edit_trace = _trace(
        session,
        message,
        provider="ollama",
        model="codellama:13b",
        context={
            "subtask_model_role": "code_generation",
            "reasoning_stage": "executor",
        },
        tools=[
            {"tool_name": "code_search", "status": "success", "duration_ms": 40, "result": {}},
            {"tool_name": "run_test_suite", "status": "success", "duration_ms": 310, "result": {"ok": True}},
            {"tool_name": "lint_and_format_workspace", "status": "success", "duration_ms": 220, "result": {"ok": True}},
        ],
        raw_output=_ollama_run("codellama:13b", 700),
        usage={"request_duration_ms": 700},
    )
    return [repo_trace, edit_trace]


def _penalty_traces(session, message):
    """A productive edit turn, a transitional stall and a runtime fallback failure."""
    productive_trace = _trace(
        session,
        message,
        provider="ollama",
        model="codellama:13b",
        context={"subtask_model_role": "code_generation"},
        tools=[
            {"tool_name": "code_search", "status": "success", "result": {}},
            {"tool_name": "run_test_suite", "status": "success", "result": {"ok": True}},
            {"tool_name": "lint_and_format_workspace", "status": "success", "result": {"ok": True}},
        ],
        raw_output={
            "runtime_attempts": [
                {"status": "success", "provider": "ollama", "model": "codellama:13b", "duration_ms": 800}
            ]
        },
        usage={"request_duration_ms": 800},
    )
    stalled_trace = _trace(
        session,
        message,
        provider="copilot",
        model="Claude Haiku 4.5",
        context={"subtask_model_role": "code_generation"},
        tools=[],
        raw_output={
            "content": "Let me inspect the files first.",
            "suppressed_as_transitional": True,
            "runtime_attempts": [
                {"status": "success", "provider": "copilot", "model": "Claude Haiku 4.5", "duration_ms": 3200}
            ],
        },
        usage={"request_duration_ms": 3200},
    )
    fallback_error_trace = _trace(
        session,
        message,
        provider="runtime-fallback",
        model="unresolved",
        context={"subtask_model_role": "code_generation"},
        tools=[],
        raw_output={
            "error": "All configured runtime targets failed",
            "runtime_attempts": [
                {
                    "status": "error",
                    "provider": "openrouter",
                    "model": "stepfun/step-3.5-flash:free",
                    "duration_ms": 500,
                    "target_id": "target-stepfun",
                }
            ],
        },
        usage={},
    )
    return [productive_trace, stalled_trace, fallback_error_trace]


@pytest.mark.asyncio
async def test_coding_discipline_stats_and_recommendations(db):
    project, session, message = await _seed_session(
        db, name_prefix="discipline-project", description="discipline project", agent_type="change", model="gemma4:e4b"
    )
    # One review, one planning, one repo-intelligence and one edit turn, each from its own model.
    db.add_all([*_review_and_planning_traces(session, message), *_repo_and_edit_traces(session, message)])
    await db.commit()

    payload = await coding_discipline_stats(db, project_id=project.id, limit=20)

    assert "review" in payload["summary"]
    assert "planning" in payload["summary"]
    assert "repo-intelligence" in payload["summary"]
    assert any(row["discipline"] == "review" for row in payload["rows"])
    assert payload["summary"]["review"]["quality_pass_rate"] == 1.0
    edit_row = next(row for row in payload["rows"] if row["discipline"] == "edit")
    assert edit_row["verification_pass_rate"] == 1.0
    assert edit_row["tests_pass_rate"] == 1.0
    assert edit_row["formatting_pass_rate"] == 1.0
    assert edit_row["discipline_alignment_score"] is not None
    assert payload["summary"]["repo-intelligence"]["code_intelligence_rate"] == 1.0

    recommendations = await recommend_coding_models(
        db,
        project_id=project.id,
        min_turns=1,
        stats_payload=payload,
    )

    assert recommendations["review"]["model_id"] == "gemma4:e4b"
    assert "planning" not in recommendations
    assert recommendations["edit"]["model_id"] == "codellama:13b"
    assert recommendations["edit"]["confidence"] > 0
    assert "routing_reason" in recommendations["edit"]


@pytest.mark.asyncio
async def test_coding_discipline_penalizes_stalls_and_runtime_failures(db):
    project, session, message = await _seed_session(
        db,
        name_prefix="discipline-penalty",
        description="discipline penalty project",
        agent_type="coding",
        model="codellama:13b",
    )
    db.add_all(_penalty_traces(session, message))
    await db.commit()

    payload = await coding_discipline_stats(db, project_id=project.id, limit=20)

    edit_rows = [row for row in payload["rows"] if row["discipline"] == "edit"]
    productive_row = next(row for row in edit_rows if row["model_id"] == "codellama:13b")
    stalled_row = next(row for row in edit_rows if row["model_id"] == "Claude Haiku 4.5")
    failed_row = next(row for row in edit_rows if row["model_id"] == "stepfun/step-3.5-flash:free")

    assert productive_row["productive_turn_rate"] == 1.0
    assert stalled_row["transitional_stall_rate"] == 1.0
    assert stalled_row["productive_turn_rate"] == 0.0
    assert failed_row["runtime_failure_rate"] == 1.0

    recommendations = await recommend_coding_models(
        db,
        project_id=project.id,
        min_turns=1,
        stats_payload=payload,
    )

    assert recommendations["edit"]["model_id"] == "codellama:13b"
