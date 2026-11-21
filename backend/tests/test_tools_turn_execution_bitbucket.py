"""Bitbucket pull request delivery and secure work workspace updates recorded by tool calls."""

import json
import uuid
from pathlib import Path

import pytest
from sqlalchemy import select

from app.agent.core.turn.turn_diff import TurnDiffTracker
from app.agent.core.turn.turn_tools import execute_tool_call_for_turn
from app.models import (
    Message,
    Project,
    Session,
    User,
    WorkCodingPipelineRun,
    WorkCodingWorkspace,
    WorkItem,
    WorkItemChangeUnit,
    WorkPullRequest,
)
from app.tools.context import ToolContext


async def _execute_single_tool_call(
    db, *, assistant_message_id: str, tool_call: dict, tool_context: ToolContext, allowed: set[str], execute_tool
):
    return await execute_tool_call_for_turn(
        db=db,
        assistant_message_id=assistant_message_id,
        tool_call=tool_call,
        tool_context=tool_context,
        active_steps=[],
        current_step_index=0,
        current_step_tool_activity=False,
        current_allowed_tool_names=allowed,
        latest_repo_state={},
        infer_repo_tool_args=lambda tool_name, tool_args, latest_repo_state: tool_args,
        resolve_allowed_tools_for_step_tool_call=lambda **kwargs: (
            kwargs["current_step_index"],
            kwargs["current_step_tool_activity"],
            kwargs["current_allowed_tool_names"],
        ),
        compact_tool_result_for_model=lambda tool_name, result: result,
        summary_domains_satisfied_by_result=lambda tool_name, result: set(),
        execute_tool=execute_tool,
        turn_diff_tracker=TurnDiffTracker(),
        context_snapshot={},
    )


async def _seed_pr_delivery_session(db) -> tuple[User, Project, WorkItem, WorkItemChangeUnit, Session, Message]:
    actor = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    project = Project(name="turn-pr-delivery-project", config={}, is_active=True)
    db.add(project)
    await db.flush()
    item = WorkItem(
        project_id=project.id,  # the session's Workspace: an item of another one is never used
        source_type="jira",
        source_instance="risk",
        source_key="ACME-615",
        title="Clean Terraform leftovers",
        sync_state="imported",
    )
    db.add(item)
    await db.flush()
    unit = WorkItemChangeUnit(
        work_item_id=item.id,
        repository_name="service-api",
        branch_name="feature/clean-terraform",
        expected_paths_json=["terraform/base/removed.txt"],
        created_by=actor.id,
        updated_by=actor.id,
    )
    session = Session(
        user_id=actor.id,
        project_id=project.id,
        agent_type="coding",
        status="active",
        metadata_={"secure_work_execution": {"work_item_id": item.id, "change_unit_ids": [unit.id]}},
    )
    db.add_all([unit, session])
    await db.flush()
    message = Message(session_id=session.id, role="assistant", content="")
    db.add(message)
    await db.commit()
    return actor, project, item, unit, session, message


@pytest.mark.asyncio
async def test_execute_tool_call_for_turn_records_bitbucket_pr_delivery(db):
    actor, project, item, unit, session, message = await _seed_pr_delivery_session(db)

    async def fake_execute_tool(tool_name, tool_args, tool_context):
        assert tool_name == "create_bitbucket_pull_request"
        return {
            "status": "created",
            "id": 77,
            "title": tool_args["title"],
            "state": "OPEN",
            "from_branch": tool_args["from_branch"],
            "to_branch": "master",
            "reviewers": [{"name": "reviewerbb", "approved": False}],
            "links": "https://bitbucket.example/projects/PROJ/repos/service-api/pull-requests/77",
        }

    executed = await _execute_single_tool_call(
        db,
        assistant_message_id=message.id,
        tool_call={
            "id": "call-pr-1",
            "function": {
                "name": "create_bitbucket_pull_request",
                "arguments": json.dumps(
                    {
                        "project_key": "PROJ",
                        "repo_slug": "service-api",
                        "title": "ACME-615 clean Terraform leftovers",
                        "from_branch": "feature/clean-terraform",
                        "to_branch": "master",
                    }
                ),
            },
        },
        tool_context=ToolContext(
            user_id=actor.id,
            project_ids=[project.id],
            roles=["admin"],
            session_id=session.id,
            project_config={"bitbucket_url": "https://bitbucket.example"},
            db=db,
            workspace_root=str(Path.cwd()),
        ),
        allowed={"create_bitbucket_pull_request"},
        execute_tool=fake_execute_tool,
    )

    delivery = executed.tool_result["result"]["work_delivery"]
    assert delivery["status"] == "recorded"
    assert delivery["work_item_id"] == item.id
    assert delivery["change_unit_id"] == unit.id
    row = (await db.execute(select(WorkPullRequest))).scalar_one()
    assert row.work_item_id == item.id
    assert row.change_unit_id == unit.id
    assert row.repository_slug == "service-api"
    assert row.pr_id == "77"
    assert row.pr_url.endswith("/pull-requests/77")
    assert row.status == "open"


async def _seed_empty_prepared_workspace(db) -> tuple[User, Session, WorkItemChangeUnit, WorkCodingWorkspace]:
    actor = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    session = Session(user_id=actor.id, agent_type="coding", status="running", metadata_={})
    item = WorkItem(
        source_type="jira",
        source_instance="risk",
        source_key="ACME-615",
        title="Cleaning Terraform and Helm Config",
        work_state="ready_for_implementation",
        sync_state="imported",
    )
    db.add_all([session, item])
    await db.flush()
    unit = WorkItemChangeUnit(
        work_item_id=item.id,
        repository_name="aws-shop-infrastructure",
        branch_name="feature/ACME-615-clean-base-terraform-leftovers",
        scope="Clean Terraform base leftovers.",
        status="planned",
        created_by=actor.id,
    )
    run = WorkCodingPipelineRun(work_item_id=item.id, status="running", control_state="running", started_by=actor.id)
    db.add_all([unit, run])
    await db.flush()
    workspace = WorkCodingWorkspace(
        work_item_id=item.id,
        pipeline_run_id=run.id,
        change_unit_id=unit.id,
        session_id=session.id,
        provider="bitbucket",
        provider_instance="risk",
        project_key="SHOP",
        repository_name="aws-shop-infrastructure",
        repository_slug="aws-shop-infrastructure",
        repository_url="https://bitbucket.example.test/projects/SHOP/repos/aws-shop-infrastructure",
        base_branch="master",
        resolved_base_branch="master",
        feature_branch=unit.branch_name,
        workspace_path="/tmp/octryx-empty-workspace",
        restart_generation=0,
        status="prepared_empty",
        evidence_json={"clone_performed": False},
        is_active=True,
        created_by=actor.id,
        updated_by=actor.id,
    )
    db.add(workspace)
    await db.flush()
    return actor, session, unit, workspace


@pytest.mark.asyncio
async def test_execute_tool_call_for_turn_updates_secure_work_workspace_after_bitbucket_prepare(db):
    actor, session, unit, workspace = await _seed_empty_prepared_workspace(db)

    async def fake_execute_tool(_tool_name, _tool_args, _tool_context):
        return {
            "project_key": "SHOP",
            "repo_slug": "aws-shop-infrastructure",
            "local_path": "/tmp/octryx/coding-runs/ACME-615/repo",
            "relative_path": "var/repos/bitbucket/SHOP/aws-shop-infrastructure",
            "base_branch": "master",
            "branch_name": unit.branch_name,
            "cloned": True,
            "fallback_used": False,
            "attempted_base_branches": ["master"],
            "remote_url": "https://***@bitbucket.example.test/scm/SHOP/aws-shop-infrastructure.git",
            "head_commit": "abc1234567890",
        }

    executed = await _execute_single_tool_call(
        db,
        assistant_message_id=str(uuid.uuid4()),
        tool_call={
            "id": "call-prepare-bitbucket",
            "function": {
                "name": "prepare_bitbucket_repository",
                "arguments": json.dumps(
                    {
                        "project_key": "SHOP",
                        "repo_slug": "aws-shop-infrastructure",
                        "branch_name": unit.branch_name,
                    }
                ),
            },
        },
        tool_context=ToolContext(
            user_id=actor.id,
            project_ids=[],
            roles=["admin"],
            session_id=session.id,
            project_config={},
            db=db,
            workspace_root="/tmp/octryx/coding-runs/ACME-615",
        ),
        allowed=set(),
        execute_tool=fake_execute_tool,
    )

    await db.refresh(workspace)
    assert executed.latest_repo_state["local_path"] == "/tmp/octryx/coding-runs/ACME-615/repo"
    assert workspace.status == "prepared"
    assert workspace.workspace_path == "/tmp/octryx/coding-runs/ACME-615/repo"
    assert workspace.base_commit == "abc1234567890"
    assert workspace.evidence_json["clone_reason"] == "prepare_bitbucket_repository_tool"
    assert workspace.evidence_json["prepare_bitbucket_repository"]["branch_name"] == unit.branch_name
