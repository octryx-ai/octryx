"""Restarting a coding agent execution creates a fresh audited session, and a start materializes a local git workspace."""

from __future__ import annotations

import subprocess
from pathlib import Path

from sqlalchemy import select

from app.models import CodeRepository, Session, WorkCodingAuditEvent, WorkCodingWorkspace, WorkRepositoryProfile
from app.services.secure_work.coding.coding_execution import start_work_item_coding_agent_execution
from tests.secure_work_coding_execution_support import _actor, _approved_plan_and_unit, _work_item


async def test_restart_work_item_coding_agent_execution_creates_fresh_audited_session(db):
    actor = await _actor(db)
    item = await _work_item(db, source_key="ACME-617")
    plan, unit = await _approved_plan_and_unit(db, actor, item)
    captured: dict[str, str] = {}

    async def fake_start_chat_turn(**kwargs):
        captured["idempotency_key"] = kwargs["idempotency_key"]
        captured["prompt"] = kwargs["prompt"]
        captured["session_metadata_patch"] = kwargs["session_metadata_patch"]
        session = Session(
            user_id=kwargs["user"].id,
            project_id=kwargs["project_id"] or None,
            agent_type=kwargs["agent_type"],
            status="running",
            metadata_={},
        )
        kwargs["db"].add(session)
        await kwargs["db"].flush()
        return session

    result = await start_work_item_coding_agent_execution(
        db,
        work_item_id=item.id,
        current_user=actor,
        payload={
            "change_plan_id": plan.id,
            "change_unit_ids": [unit.id],
            "restart_from_scratch": True,
            "restart_reason": "PR was declined after review.",
        },
        start_chat_turn_func=fake_start_chat_turn,
    )

    assert result["status"] == "started"
    # Restart keys are shortened (sessions.idempotency_key is VARCHAR(100));
    # uniqueness per restart comes from the random suffix.
    assert captured["idempotency_key"].startswith(f"work-coding-restart:{item.id}:")
    assert len(captured["idempotency_key"]) <= 100
    assert "Operator requested restart from scratch" in captured["prompt"]
    assert captured["session_metadata_patch"]["coding_workspace_records"][0]["restart_generation"] == 1
    event = (
        await db.execute(
            select(WorkCodingAuditEvent).where(
                WorkCodingAuditEvent.work_item_id == item.id,
                WorkCodingAuditEvent.event_type == "agent_execution_restarted",
            )
        )
    ).scalar_one()
    assert event.evidence_json["session_id"] == result["session"]["id"]
    assert event.evidence_json["restart_from_scratch"] is True
    assert event.evidence_json["restart_reason"] == "PR was declined after review."
    workspace = (
        await db.execute(
            select(WorkCodingWorkspace).where(
                WorkCodingWorkspace.work_item_id == item.id,
                WorkCodingWorkspace.pipeline_run_id == result["pipeline_run"]["id"],
                WorkCodingWorkspace.change_unit_id == unit.id,
            )
        )
    ).scalar_one()
    assert workspace.restart_generation == 1
    assert workspace.is_active is True


async def test_start_work_item_coding_agent_execution_materializes_local_git_workspace(db, tmp_path):
    actor = await _actor(db)
    item = await _work_item(db, source_key="ACME-618")
    source_repo = tmp_path / "aws-shop-infrastructure"
    source_repo.mkdir()
    (source_repo / "README.md").write_text("fixture\n", encoding="utf-8")
    subprocess.run(["git", "init", "-b", "main"], cwd=source_repo, check=True, capture_output=True, text=True)
    subprocess.run(["git", "add", "README.md"], cwd=source_repo, check=True, capture_output=True, text=True)
    subprocess.run(
        ["git", "-c", "user.name=OE Test", "-c", "user.email=oe@example.test", "commit", "-m", "Initial fixture"],
        cwd=source_repo,
        check=True,
        capture_output=True,
        text=True,
    )
    repository = CodeRepository(
        name="aws-shop-infrastructure",
        repo_root=str(source_repo),
        provider="local",
        remote_url=str(source_repo),
        default_branch="main",
        is_active=True,
    )
    db.add(repository)
    await db.flush()
    profile = WorkRepositoryProfile(
        name="aws-shop-infrastructure",
        provider="local",
        repository_url=str(source_repo),
        default_branch="main",
        pr_target_branch="main",
        code_repository_id=repository.id,
        service_description="Fixture repository",
        owners_json=["platform"],
        default_reviewers_json=["reviewer"],
        build_commands_json=["true"],
        test_commands_json=["true"],
        lint_commands_json=["true"],
        format_commands_json=["true"],
        package_commands_json=["true"],
        local_run_commands_json=["true"],
        important_paths_json=["."],
        protected_paths_json=["."],
        artifact_paths_json=["."],
        test_report_paths_json=["."],
        created_by=actor.id,
        updated_by=actor.id,
    )
    db.add(profile)
    await db.flush()
    plan, unit = await _approved_plan_and_unit(db, actor, item)
    unit.repository_profile_id = profile.id

    async def fake_start_chat_turn(**kwargs):
        session = Session(
            user_id=kwargs["user"].id,
            project_id=kwargs["project_id"] or None,
            agent_type=kwargs["agent_type"],
            status="running",
            metadata_={},
        )
        kwargs["db"].add(session)
        await kwargs["db"].flush()
        return session

    result = await start_work_item_coding_agent_execution(
        db,
        work_item_id=item.id,
        current_user=actor,
        payload={"change_plan_id": plan.id, "change_unit_ids": [unit.id]},
        start_chat_turn_func=fake_start_chat_turn,
    )

    workspace = (
        await db.execute(select(WorkCodingWorkspace).where(WorkCodingWorkspace.work_item_id == item.id))
    ).scalar_one()
    assert result["workspaces"][0]["status"] == "prepared"
    assert workspace.status == "prepared"
    assert workspace.base_commit
    assert workspace.evidence_json["clone_performed"] is True
    assert workspace.evidence_json["clone_reason"] == "local_git_source_repository"
    assert (source_repo / ".git").exists()
    assert (Path(workspace.workspace_path) / ".git").exists()
    branch = subprocess.run(
        ["git", "branch", "--show-current"],
        cwd=workspace.workspace_path,
        check=True,
        capture_output=True,
        text=True,
    )
    assert branch.stdout.strip() == unit.branch_name
