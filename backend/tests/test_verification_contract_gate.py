"""The step and phase machines use the verification contract as their completion gate, and governed validation commands run only as the contract binds them."""

from __future__ import annotations

import pytest

from app.services.workflow_contracts.agent_definition import build_workflow_agent_definition


def test_step_machine_uses_contract_as_completion_gate():
    definition = build_workflow_agent_definition(
        {
            "workflow_id": "coding_change_tdd",
            "topic": "terraform cleanup",
            "verification_contract": {
                "commands": [
                    {"command": "terraform fmt -check -recursive terraform", "source": "change_unit"},
                    {"command": "test ! -d terraform/todelete", "source": "change_unit"},
                ]
            },
            "delivery": {"source_control_provider": "bitbucket", "ticket_provider": "jira"},
        }
    )
    step = definition["steps"][0]
    assert "run_validation_commands" in step["allowedTools"]
    assert "run_validation_commands" in step["successCriteria"]
    assert "run_test_suite" not in step["successCriteria"]
    assert "move to editing" in step["instructions"].lower() or "move to editing" in step["instructions"]

    # Contract runs with known providers get an explicit delivery hand-off step.
    assert [s["name"] for s in definition["steps"]] == ["Implement And Verify Change", "Deliver Change"]
    delivery = definition["steps"][1]
    assert "create_bitbucket_pull_request" in delivery["allowedTools"]
    assert "add_jira_comment" in delivery["allowedTools"]
    assert "edit_workspace_file" not in delivery["allowedTools"]
    # Delivery tools are NOT offered during implementation.
    assert "commit_and_push_repository_branch" not in definition["steps"][0]["allowedTools"]

    # Unknown providers: no delivery step, never a guessed toolset.
    no_provider = build_workflow_agent_definition(
        {
            "workflow_id": "coding_change_tdd",
            "topic": "terraform cleanup",
            "verification_contract": {"commands": [{"command": "true", "source": "change_unit"}]},
            "delivery": {"source_control_provider": "github", "ticket_provider": "jira"},
        }
    )
    assert [s["name"] for s in no_provider["steps"]] == ["Implement And Verify Change"]

    # Without a contract the classic TDD criterion stays — and no auto-delivery.
    tdd = build_workflow_agent_definition({"workflow_id": "coding_change_tdd", "topic": "java change"})
    assert "run_test_suite" in tdd["steps"][0]["successCriteria"]
    assert "run_validation_commands" not in tdd["steps"][0]["allowedTools"]
    assert [s["name"] for s in tdd["steps"]] == ["Implement And Verify Change"]


@pytest.mark.asyncio
async def test_run_validation_commands_is_bound_to_contract(db, tmp_path):
    import uuid

    from sqlalchemy import select

    from app.models import Project, Session, User
    from app.tools.context import ToolContext
    from app.tools.runtime_impl._runtime_validation_commands import RunValidationCommandsTool

    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    project = (await db.execute(select(Project))).scalars().first()
    (tmp_path / "ok.txt").write_text("ok", encoding="utf-8")
    session = Session(
        id=str(uuid.uuid4()),
        user_id=admin.id,
        project_id=project.id,
        agent_type="coding",
        status="active",
        metadata_={
            "secure_work_execution": {
                "verification_contract": {
                    "commands": [
                        {"command": "test -f ok.txt", "source": "change_unit"},
                        {"command": "test ! -f missing.txt", "source": "change_unit"},
                    ]
                }
            }
        },
    )
    db.add(session)
    await db.flush()

    context = ToolContext(
        user_id=admin.id,
        project_ids=[project.id],
        roles=["admin"],
        session_id=session.id,
        project_config={},
        db=db,
        workspace_root=str(tmp_path),
    )
    tool = RunValidationCommandsTool()
    result = await tool.execute({}, context)
    assert result.get("all_green") is True
    assert result["command_count"] == 2

    # A failing contract command yields all_green=false with the exit code.
    session.metadata_ = {
        "secure_work_execution": {
            "verification_contract": {"commands": [{"command": "test -f missing.txt", "source": "change_unit"}]}
        }
    }
    await db.flush()
    result = await tool.execute({}, context)
    assert result.get("all_green") is False
    assert result["results"][0]["exit_code"] == 1

    # No contract -> explicit refusal pointing to run_test_suite.
    session.metadata_ = {"secure_work_execution": {}}
    await db.flush()
    result = await tool.execute({}, context)
    assert "No verification contract" in result.get("error", "")

    # cwd outside the workspace is rejected.
    session.metadata_ = {
        "secure_work_execution": {
            "verification_contract": {"commands": [{"command": "true", "source": "change_unit"}]}
        }
    }
    await db.flush()
    result = await tool.execute({"cwd": "/tmp"}, context)
    assert "inside the session workspace" in result.get("error", "")


@pytest.mark.asyncio
async def test_completion_gate_blocks_unverified_contract(db):
    import uuid as _uuid

    from app.models import ToolCall
    from app.services.session.completion_quality import unverified_verification_contract_summary

    session_id = str(_uuid.uuid4())
    metadata = {
        "secure_work_execution": {
            "verification_contract": {"commands": [{"command": "true", "source": "change_unit"}]}
        }
    }

    # Contract present, never run -> blocker (this is the no-op-claim guard).
    blocker = await unverified_verification_contract_summary(
        db, session_id=session_id, session_metadata=metadata
    )
    assert blocker["reason"] == "verification_contract_not_run"

    # Red contract run -> blocker with failing commands.
    db.add(
        ToolCall(
            id=str(_uuid.uuid4()),
            session_id=session_id,
            tool_name="run_validation_commands",
            parameters={},
            result={"all_green": False, "results": [{"command": "true", "ok": False}]},
            status="success",
        )
    )
    await db.flush()
    blocker = await unverified_verification_contract_summary(
        db, session_id=session_id, session_metadata=metadata
    )
    assert blocker["reason"] == "verification_contract_failed"
    assert blocker["failing_commands"] == ["true"]

    # Green contract run -> no blocker.
    db.add(
        ToolCall(
            id=str(_uuid.uuid4()),
            session_id=session_id,
            tool_name="run_validation_commands",
            parameters={},
            result={"all_green": True, "results": []},
            status="success",
        )
    )
    await db.flush()
    assert (
        await unverified_verification_contract_summary(
            db, session_id=session_id, session_metadata=metadata
        )
        is None
    )

    # No contract -> gate inactive.
    assert (
        await unverified_verification_contract_summary(db, session_id=session_id, session_metadata={})
        is None
    )


def test_phase_machine_carries_the_contract():
    from app.agent.core.guards.tdd_cycle import (
        build_initial_tdd_cycle_state,
        is_tdd_cycle_complete,
        record_tdd_cycle_tool_result,
        resolve_tdd_cycle_phases,
    )

    definition = build_workflow_agent_definition(
        {
            "workflow_id": "coding_change_tdd",
            "topic": "terraform cleanup",
            "verification_contract": {"commands": [{"command": "true", "source": "change_unit"}]},
        }
    )
    step = definition["steps"][0]
    phases = resolve_tdd_cycle_phases(step)
    assert [p["name"] for p in phases] == ["verify_contract"]
    assert phases[0]["completion_rule"] == "validation_green"

    state = build_initial_tdd_cycle_state(step)
    assert is_tdd_cycle_complete(state) is False
    # Red validation run does not complete the phase.
    record_tdd_cycle_tool_result(state, "run_validation_commands", {"all_green": False})
    assert is_tdd_cycle_complete(state) is False
    # Green validation run completes the cycle.
    record_tdd_cycle_tool_result(state, "run_validation_commands", {"all_green": True})
    assert is_tdd_cycle_complete(state) is True
