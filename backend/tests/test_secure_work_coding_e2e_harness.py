from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import select

from app.agent.core.turn.turn_diff import TurnDiffTracker
from app.agent.core.turn.turn_tools import execute_tool_call_for_turn
from app.models import (
    Message,
    Project,
    Session,
    ToolCall,
    User,
    WorkItemChangeUnit,
    WorkPullRequest,
)
from app.tools.context import ToolContext
from app.tools.registry import execute_tool
from tests.secure_work_coding_e2e_harness_support import (
    create_fixture_remote,
    patch_fixture_bitbucket,
    seed_fixture_project,
    start_fixture_coding_session,
)


async def _run_agent_tool(
    *,
    db,
    message: Message,
    tool_context: ToolContext,
    latest_repo_state: dict[str, str],
    tool_history: list[dict[str, Any]],
    tool_name: str,
    tool_args: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, str]]:
    executed = await execute_tool_call_for_turn(
        db=db,
        assistant_message_id=message.id,
        tool_call={
            "id": f"call-{len(tool_history) + 1}",
            "function": {"name": tool_name, "arguments": json.dumps(tool_args)},
        },
        tool_context=tool_context,
        active_steps=[],
        current_step_index=0,
        current_step_tool_activity=False,
        current_allowed_tool_names={tool_name},
        latest_repo_state=latest_repo_state,
        infer_repo_tool_args=lambda _tool_name, args, _latest_repo_state: args,
        resolve_allowed_tools_for_step_tool_call=lambda **kwargs: (
            kwargs["current_step_index"],
            kwargs["current_step_tool_activity"],
            kwargs["current_allowed_tool_names"],
        ),
        compact_tool_result_for_model=lambda _tool_name, result: result,
        summary_domains_satisfied_by_result=lambda _tool_name, _result: set(),
        execute_tool=execute_tool,
        turn_diff_tracker=TurnDiffTracker(),
        context_snapshot={},
        turn_tool_history=tool_history,
    )
    result = executed.tool_result["result"]
    tool_history.append({"tool_name": tool_name, "result": result})
    assert "error" not in result, f"{tool_name} failed: {result}"
    return result, executed.latest_repo_state


async def _open_assistant_message(db, session_id: str) -> tuple[Session, Message]:
    session = await db.get(Session, session_id)
    assert session is not None
    message = Message(session_id=session.id, role="assistant", content="")
    db.add(message)
    await db.commit()
    return session, message


def _agent_turn(db, message: Message, actor: User, project: Project, session: Session, tmp_path: Path) -> dict:
    """The state one agent turn threads through its tool calls (latest repo state, tool history)."""
    tool_context = ToolContext(
        user_id=actor.id,
        project_ids=[project.id],
        roles=["admin"],
        session_id=session.id,
        project_config=project.config,
        db=db,
        workspace_root=str(tmp_path / "session-workspace"),
        capability_type="coding",
    )
    return {"db": db, "message": message, "tool_context": tool_context, "latest_repo_state": {}, "tool_history": []}


async def _run_turn_tool(turn: dict[str, Any], tool_name: str, tool_args: dict[str, Any]) -> dict[str, Any]:
    result, turn["latest_repo_state"] = await _run_agent_tool(
        db=turn["db"],
        message=turn["message"],
        tool_context=turn["tool_context"],
        latest_repo_state=turn["latest_repo_state"],
        tool_history=turn["tool_history"],
        tool_name=tool_name,
        tool_args=tool_args,
    )
    return result


async def _prepare_and_edit(turn: dict[str, Any], unit: WorkItemChangeUnit) -> dict[str, Any]:
    prepare_result = await _run_turn_tool(
        turn,
        "prepare_bitbucket_repository",
        {
            "project_key": "SHOP",
            "repo_slug": "aws-shop-infrastructure",
            "base_branch": "main",
            "branch_name": unit.branch_name,
        },
    )
    repo_relative_path = prepare_result["relative_path"]
    cleanup_file = f"{repo_relative_path}/terraform/base/removed.txt"

    edit_result = await _run_turn_tool(
        turn,
        "edit_workspace_file",
        {
            "path": cleanup_file,
            "old_string": (
                "remove: legacy base pipeline terraform block\n"
                "remove: obsolete helm values injection\n"
            ),
            "new_string": "removed: legacy base pipeline cleanup moved to split pipeline\n",
        },
    )
    assert edit_result["status"] == "edited"
    return prepare_result


async def _validate_and_commit(turn: dict[str, Any], unit: WorkItemChangeUnit, prepare_result) -> dict[str, Any]:
    validation_result = await _run_turn_tool(
        turn,
        # The coding delivery gate accepts only the governed verification contract,
        # proven in this session by run_validation_commands (all_green); an ad-hoc
        # CLI run of the same command is no proof.
        "run_validation_commands",
        {"cwd": prepare_result["local_path"]},
    )
    assert validation_result["all_green"] is True
    assert [(entry["command"], entry["exit_code"]) for entry in validation_result["results"]] == [
        ("git diff --check", 0)
    ]

    commit_result = await _run_turn_tool(
        turn,
        "commit_and_push_repository_branch",
        {
            "local_path": prepare_result["local_path"],
            "repo_slug": "aws-shop-infrastructure",
            "branch_name": unit.branch_name,
            "commit_message": "ACME-615 clean base pipeline leftovers",
        },
    )
    assert commit_result["status"] == "pushed"
    return commit_result


async def _open_pull_request(turn: dict[str, Any], unit: WorkItemChangeUnit) -> dict[str, Any]:
    return await _run_turn_tool(
        turn,
        "create_bitbucket_pull_request",
        {
            "project_key": "SHOP",
            "repo_slug": "aws-shop-infrastructure",
            "title": "ACME-615 clean base pipeline leftovers",
            "from_branch": unit.branch_name,
            "to_branch": "main",
            "description": "Implements the approved Octryx fixture-backed change plan.",
        },
    )


async def _assert_pull_request_recorded(db, start_result, unit, pr_result, post_payloads) -> WorkPullRequest:
    assert pr_result["status"] == "created"
    assert pr_result["work_delivery"]["status"] == "recorded"
    assert post_payloads[0]["reviewers"] == [{"user": {"name": "reviewerbb"}}]
    await db.refresh(unit)
    row = (await db.execute(select(WorkPullRequest))).scalar_one()
    assert row.work_item_id == start_result["work_item_id"]
    assert row.change_unit_id == unit.id
    assert row.repository_slug == "aws-shop-infrastructure"
    assert row.source_branch == unit.branch_name
    assert row.target_branch == "main"
    assert row.pr_id == "77"
    assert row.pr_url.endswith("/pull-requests/77")  # D12: the PR lives in work_pull_requests, linked by unit id
    return row


async def _assert_tool_calls_persisted_in_order(db, message: Message) -> None:
    persisted_tool_names = [
        row.tool_name
        for row in (
            await db.execute(select(ToolCall).where(ToolCall.message_id == message.id).order_by(ToolCall.created_at))
        ).scalars()
    ]
    assert persisted_tool_names == [
        "prepare_bitbucket_repository",
        "edit_workspace_file",
        "run_validation_commands",
        "commit_and_push_repository_branch",
        "create_bitbucket_pull_request",
    ]


def _budget_report(start_result, commit_result, row, post_payloads, tool_history) -> dict[str, Any]:
    return {
        "request": {
            "source_key": "ACME-615",
            "title": "Cleaning Terraform and Helm Config",
            "session_url": start_result["session"]["chat_url"],
        },
        "output": {
            "branch": commit_result["branch_name"],
            "head_commit": commit_result["head_commit"],
            "pr_url": row.pr_url,
            "reviewers": [reviewer["user"]["name"] for reviewer in post_payloads[0]["reviewers"]],
        },
        "evidence": [
            {
                "tool_name": entry["tool_name"],
                "status": entry["result"].get("status")
                or entry["result"].get("exit_code")
                or entry["result"].get("all_green")
                or entry["result"].get("applied"),
            }
            for entry in tool_history
        ],
        "budget": {
            "llm_calls": 0,
            "input_tokens": 0,
            "output_tokens": 0,
            "tool_calls": len(tool_history),
            "max_tool_calls": 8,
            "within_budget": len(tool_history) <= 8,
        },
    }


@pytest.mark.asyncio
async def test_fixture_backed_coding_flow_reaches_pr_with_budget_report(db, monkeypatch, tmp_path):
    remote = create_fixture_remote(tmp_path)
    actor = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    project = await seed_fixture_project(db, actor)

    start_result, unit = await start_fixture_coding_session(db, actor, project)
    session, message = await _open_assistant_message(db, start_result["session"]["id"])
    post_payloads = patch_fixture_bitbucket(monkeypatch, remote)

    turn = _agent_turn(db, message, actor, project, session, tmp_path)
    prepare_result = await _prepare_and_edit(turn, unit)
    commit_result = await _validate_and_commit(turn, unit, prepare_result)
    pr_result = await _open_pull_request(turn, unit)

    row = await _assert_pull_request_recorded(db, start_result, unit, pr_result, post_payloads)
    await _assert_tool_calls_persisted_in_order(db, message)

    report = _budget_report(start_result, commit_result, row, post_payloads, turn["tool_history"])
    assert report["budget"] == {
        "llm_calls": 0,
        "input_tokens": 0,
        "output_tokens": 0,
        "tool_calls": 5,
        "max_tool_calls": 8,
        "within_budget": True,
    }
    assert report["output"]["pr_url"].endswith("/pull-requests/77")
