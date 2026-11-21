"""Fixture git remote, seeded project and work item, and faked Bitbucket API for the coding end-to-end harness."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from sqlalchemy import select

from app.models import (
    CodeRepository,
    Project,
    Session,
    User,
    WorkChangePlan,
    WorkItem,
    WorkItemChangeUnit,
    WorkRepositoryProfile,
)
from app.services.secure_work.coding.coding_execution import start_work_item_coding_agent_execution
from app.time_utils import utc_now


def _git(cwd: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        text=True,
        capture_output=True,
    )
    return result.stdout.strip()


def create_fixture_remote(tmp_path: Path) -> Path:
    source = tmp_path / "source"
    source.mkdir()
    _git(source, "init", "-b", "main")
    _git(source, "config", "user.email", "fixture@example.test")
    _git(source, "config", "user.name", "Fixture Author")
    terraform_dir = source / "terraform" / "base"
    terraform_dir.mkdir(parents=True)
    (terraform_dir / "removed.txt").write_text(
        "\n".join(
            [
                "# Base pipeline cleanup notes",
                "keep: pipeline split has moved shared deployment logic",
                "remove: legacy base pipeline terraform block",
                "remove: obsolete helm values injection",
                "",
            ]
        ),
        encoding="utf-8",
    )
    _git(source, "add", "-A")
    _git(source, "commit", "-m", "chore: seed Terraform base cleanup fixture")
    remote = tmp_path / "aws-shop-infrastructure.git"
    _git(tmp_path, "clone", "--bare", str(source), str(remote))
    return remote


def _fixture_project_config() -> dict[str, Any]:
    return {
        "bitbucket_url": "https://bitbucket.example.test",
        "bitbucket_allowed_repos": ["SHOP/aws-shop-infrastructure"],
        "managed_repo_root": "var/repos/bitbucket",
        "repository_bootstrap": {"enabled": False},
        "tool_policy": {
            "allowlist": [
                "prepare_bitbucket_repository",
                "edit_workspace_file",
                "run_validation_commands",
                "commit_and_push_repository_branch",
                "create_bitbucket_pull_request",
            ]
        },
    }


async def seed_fixture_project(db, actor: User) -> Project:
    project = Project(name="coding-e2e-fixture-project", config=_fixture_project_config(), is_active=True)
    db.add(project)
    await db.flush()
    db.add(
        CodeRepository(
            project_id=project.id,
            name="aws-shop-infrastructure",
            provider="bitbucket",
            repo_root="SHOP/aws-shop-infrastructure",
            remote_url="https://bitbucket.example.test/scm/SHOP/aws-shop-infrastructure.git",
            default_branch="main",
            config_json={"operation_policy": {"read": True, "branch": True, "write": True, "pr": True}},
        )
    )
    # The reviewer is the repository record's declared default reviewer (its runtime projection).
    db.add(
        WorkRepositoryProfile(
            name="aws-shop-infrastructure",
            project_id=project.id,
            default_reviewers_json=["reviewerbb"],
            created_by=actor.id,
            updated_by=actor.id,
        )
    )
    await db.commit()
    return project


async def _seed_fixture_work_item(db, project: Project) -> WorkItem:
    item = WorkItem(
        project_id=project.id,
        source_type="jira",
        source_instance="risk",
        source_key="ACME-615",
        source_project_key="ACME",
        source_url="https://jira.example.test/browse/ACME-615",
        title="Cleaning Terraform and Helm Config",
        description=(
            "Clean legacy Terraform and Helm base pipeline leftovers after the deployment pipeline split."
        ),
        issue_type="Task",
        source_status="Open",
        work_state="ready_for_implementation",
        sync_state="imported",
        labels_json=["octryx"],
    )
    db.add(item)
    await db.flush()
    return item


async def _seed_fixture_change_unit(db, item: WorkItem, actor: User) -> WorkItemChangeUnit:
    record = (await db.execute(select(WorkRepositoryProfile).where(
        WorkRepositoryProfile.name == "aws-shop-infrastructure"))).scalars().first()
    unit = WorkItemChangeUnit(
        work_item_id=item.id,
        repository_profile_id=record.id if record else None,
        repository_name="aws-shop-infrastructure",
        branch_name="feature/ACME-615-clean-base-terraform-leftovers",
        scope="Remove obsolete base pipeline cleanup entries from Terraform/Helm configuration evidence.",
        expected_paths_json=["terraform/base/removed.txt"],
        validation_commands_json=["git diff --check"],
        reviewer_policy_json={"required_reviewers": ["reviewerbb"]},
        status="planned",
        created_by=actor.id,
        updated_by=actor.id,
    )
    db.add(unit)
    await db.flush()
    return unit


async def _seed_approved_plan(db, item: WorkItem, unit: WorkItemChangeUnit, actor: User) -> WorkChangePlan:
    now = utc_now()
    plan = WorkChangePlan(
        work_item_id=item.id,
        version=1,
        status="approved",
        title="ACME-615 approved fixture plan",
        understood_request=(
            "Remove legacy base pipeline leftovers from the infrastructure repository and create a reviewable PR."
        ),
        change_units_json=[
            {
                "id": unit.id,
                "repository_name": unit.repository_name,
                "branch_name": unit.branch_name,
                "expected_paths": list(unit.expected_paths_json or []),
            }
        ],
        planned_files_json=[
            {"repository_name": unit.repository_name, "paths": list(unit.expected_paths_json or [])}
        ],
        validation_plan_json=[{"command": "git diff --check"}],
        required_approvals_json=[{"type": "work_plan", "required": True}],
        rollback_plan="Decline or revert the generated pull request.",
        evidence_json={"source": "fixture-backed-coding-e2e"},
        created_by=actor.id,
        updated_by=actor.id,
        approved_by=actor.id,
        decided_by=actor.id,
        approved_at=now,
        decided_at=now,
    )
    db.add(plan)
    await db.flush()
    return plan


async def _fake_start_chat_turn(**kwargs):
    session = Session(
        user_id=kwargs["user"].id,
        project_id=kwargs["project_id"] or None,
        agent_type=kwargs["agent_type"],
        status="running",
        metadata_=dict(kwargs.get("session_metadata_patch") or {}),
    )
    kwargs["db"].add(session)
    await kwargs["db"].flush()
    return session


async def start_fixture_coding_session(db, actor: User, project: Project) -> tuple[dict[str, Any], WorkItemChangeUnit]:
    item = await _seed_fixture_work_item(db, project)
    unit = await _seed_fixture_change_unit(db, item, actor)
    plan = await _seed_approved_plan(db, item, unit, actor)

    result = await start_work_item_coding_agent_execution(
        db,
        work_item_id=item.id,
        current_user=actor,
        payload={"change_plan_id": plan.id, "change_unit_ids": [unit.id]},
        start_chat_turn_func=_fake_start_chat_turn,
    )
    assert result["session"]["chat_url"] == f"/chat?session_id={result['session']['id']}"
    return result, unit


def patch_fixture_bitbucket(monkeypatch, remote: Path) -> list[dict[str, Any]]:
    """Points the Bitbucket clone at the fixture remote and fakes the PR API; returns the posted PR payloads."""
    monkeypatch.setattr(
        "app.tools.bitbucket_impl._bitbucket_sync_repo._bitbucket_clone_url",
        # A URL, not a bare path: a local-path origin is the platform's repository
        # mirror, whose push is chased on to the mirror's own remote. The
        # fixture remote stands in for the real Bitbucket remote, so it is addressed
        # like one.
        lambda *_args, **_kwargs: remote.as_uri(),
    )
    async def fake_detect_default_branch(*_args, **_kwargs):
        return "main"

    monkeypatch.setattr("app.tools.bitbucket_impl._bitbucket_sync_repo._detect_default_branch", fake_detect_default_branch)

    post_payloads: list[dict[str, Any]] = []

    async def fake_pr_get(*_args, **_kwargs):
        return {"values": []}

    async def fake_pr_post(_context, _path, *, payload):
        post_payloads.append(payload)
        from_branch = str(payload["fromRef"]["id"]).removeprefix("refs/heads/")
        to_branch = str(payload["toRef"]["id"]).removeprefix("refs/heads/")
        return {
            "id": 77,
            "title": payload["title"],
            "state": "OPEN",
            "fromRef": {"displayId": from_branch},
            "toRef": {"displayId": to_branch},
            "reviewers": [{"user": {"displayName": "Review Expert"}, "approved": False}],
            "links": {
                "self": [
                    {
                        "href": (
                            "https://bitbucket.example.test/projects/SHOP/repos/"
                            "aws-shop-infrastructure/pull-requests/77"
                        )
                    }
                ]
            },
        }, 201

    monkeypatch.setattr("app.tools.bitbucket_impl._bitbucket_internal_network._bitbucket_json_get", fake_pr_get)
    monkeypatch.setattr("app.tools.bitbucket_impl._bitbucket_pull_requests._bitbucket_json_post", fake_pr_post)
    return post_payloads
