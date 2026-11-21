from __future__ import annotations

from sqlalchemy import select

from app.models import Session, User, WorkCodingAuditEvent, WorkItem, WorkItemChangeUnit
from app.services.secure_work.plans.repository_planning import suggest_branch_name
from app.time_utils import utc_now
from tests.repository_record_support import create_repository_record, update_repository_record


def _work_item(**overrides) -> WorkItem:
    payload = {
        "source_type": "jira",
        "source_instance": "repo-plan-test",
        "source_key": "OCX-318",
        "source_project_key": "OCX",
        "title": "Add secure repository planning",
        "source_status": "Open",
        "work_state": "intake",
        "sync_state": "imported",
    }
    payload.update(overrides)
    return WorkItem(**payload)


async def _create_profile(client, auth_headers, **overrides) -> dict:
    payload = {
        "name": "acme-orders-runtime",
        "provider": "bitbucket",
        "repository_url": "https://bitbucket.example.test/projects/OCX/repos/acme-orders-runtime",
        "default_branch": "main",
        "protected_branches": ["main", "release/*"],
        "jira_project_keys": ["OCX"],
        "service_description": "Runtime services for secure work execution.",
        "owners": ["platform-team"],
        "default_reviewers": ["alice", "bob"],
        "branch_naming_rule": "feature/{key}-{slug}",
        "pr_target_branch": "main",
        "required_pipelines": ["build", "security"],
        "required_tests": ["npm run lint", "npm run build"],
        "setup_commands": ["corepack enable"],
        "build_commands": ["npm run build"],
        "test_commands": ["npm test"],
        "lint_commands": ["npm run lint"],
        "format_commands": ["npm run format:check"],
        "package_commands": ["npm run package"],
        "local_run_commands": ["npm run dev"],
        "cleanup_commands": ["rm -rf dist"],
        "builder_runtime_image": "node:22-bookworm",
        "local_toolchain": ["node 22", "npm 10"],
        "required_env_vars": ["NODE_ENV"],
        "secret_references": ["NPM_TOKEN"],
        "protected_paths": ["backend/app/runtime/**"],
        "hotspot_files": ["frontend/chat/src/App.tsx"],
        "artifact_paths": ["dist/**"],
        "coverage_report_paths": ["coverage/lcov.info"],
        "test_report_paths": ["reports/junit.xml"],
        "multi_repo_dependencies": [{"repository": "acme-orders-ui", "order": 2, "reason": "API contract consumer"}],
        "risk_tags": ["runtime"],
        "important_paths": ["backend/app/services", "frontend/chat/src"],
        "review_status": "reviewed",
    }
    payload.update(overrides)
    return await create_repository_record(payload)  # The record's coding setup, not a Work profile


async def test_repository_profile_create_update_and_serialization(client, auth_headers):
    profile = await _create_profile(client, auth_headers)

    assert profile["name"] == "acme-orders-runtime"
    assert profile["owners"] == ["platform-team"]
    assert profile["default_reviewers"] == ["alice", "bob"]
    assert profile["required_tests"] == ["npm run lint", "npm run build"]
    assert profile["build_commands"] == ["npm run build"]
    assert profile["test_commands"] == ["npm test"]
    assert profile["lint_commands"] == ["npm run lint"]
    assert profile["format_commands"] == ["npm run format:check"]
    assert profile["package_commands"] == ["npm run package"]
    assert profile["local_run_commands"] == ["npm run dev"]
    assert profile["builder_runtime_image"] == "node:22-bookworm"
    assert profile["secret_references"] == ["NPM_TOKEN"]
    assert profile["multi_repo_dependencies"][0]["repository"] == "acme-orders-ui"

    # The coding setup is saved on the repository record; the projection follows.
    updated = await update_repository_record(profile["id"], {"owners": ["runtime-owner"]})
    assert updated["owners"] == ["runtime-owner"]
    assert updated["review_status"] == "reviewed" and updated["profile_source"] == "code_repository"
    assert updated["jira_project_keys"] == [], "D3: no Jira project keys on the repository"


async def test_change_unit_planning_suggests_branch_and_persists_multi_repo_units(client, auth_headers, db):
    profile_a = await _create_profile(client, auth_headers, name="acme-orders-runtime")
    profile_b = await _create_profile(
        client,
        auth_headers,
        name="acme-orders-ui",
        repository_url="https://bitbucket.example.test/projects/OCX/repos/acme-orders-ui",
        important_paths=["frontend/chat/src"],
        build_commands=["npm run build --workspace chat"],
        test_commands=["npm test --workspace chat"],
        lint_commands=["npm run lint --workspace chat"],
        format_commands=["npm run format:check --workspace chat"],
        package_commands=["npm run package --workspace chat"],
        local_run_commands=["npm run dev --workspace chat"],
    )
    item = _work_item(title="Add reviewer policy to work board")
    db.add(item)
    await db.commit()

    response = await client.post(
        f"/api/v1/secure-work/work-items/{item.id}/change-units/plan",
        headers=auth_headers,
        json={
            "units": [
                {
                    "repository_profile_id": profile_a["id"],
                    "scope": "Backend planning APIs",
                    "expected_paths": ["backend/app/services/secure_work"],
                },
                {
                    "repository_profile_id": profile_b["id"],
                    "scope": "Work detail impact map",
                    "dependency_order": 1,
                },
            ]
        },
    )

    assert response.status_code == 200, response.text
    units = response.json()["items"]
    assert len(units) == 2
    assert units[0]["repository_name"] == "acme-orders-runtime"
    assert units[0]["branch_name"] == "feature/OCX-318-add-reviewer-policy-to-work-board"
    assert units[0]["validation_commands"] == ["npm run lint", "npm test", "npm run build", "npm run package"]
    assert units[0]["reviewer_policy"]["default_reviewers"] == ["alice", "bob"]
    assert units[0]["reviewer_policy"]["target_branch"] == "main"
    assert units[0]["reviewer_policy"]["command_profile"]["local_run_commands"] == ["npm run dev"]
    assert units[1]["repository_name"] == "acme-orders-ui"
    assert units[1]["dependency_order"] == 1

    persisted = (
        await db.execute(select(WorkItemChangeUnit).where(WorkItemChangeUnit.work_item_id == item.id))
    ).scalars().all()
    assert len(persisted) == 2


async def test_coding_sessions_include_change_plan_and_unit_evidence(client, auth_headers, db):
    profile = await _create_profile(client, auth_headers, name="octryx")
    item = _work_item(source_key="OCX-777", title="Add explicit Coding Session start flow")
    db.add(item)
    await db.commit()

    units_response = await client.post(
        f"/api/v1/secure-work/work-items/{item.id}/change-units/plan",
        headers=auth_headers,
        json={
            "units": [
                {
                    "repository_profile_id": profile["id"],
                    "scope": "Coding cockpit start flow",
                    "expected_paths": ["frontend/chat/src/chat/coding"],
                    "validation_commands": ["npm run lint", "npm run build"],
                }
            ]
        },
    )
    assert units_response.status_code == 200, units_response.text

    plan_response = await client.post(
        f"/api/v1/secure-work/work-items/{item.id}/change-plans/generate",
        headers=auth_headers,
        json={"understood_request": "Create a governed Coding Session from a Work Item."},
    )
    assert plan_response.status_code == 200, plan_response.text

    sessions_response = await client.get("/api/v1/secure-work/coding-sessions?limit=100", headers=auth_headers)
    assert sessions_response.status_code == 200, sessions_response.text
    session = next(
        entry
        for entry in sessions_response.json()["items"]
        if entry["work_item"]["source_key"] == "OCX-777"
    )
    assert session["change_plans"][0]["id"] == plan_response.json()["id"]
    assert session["change_units"][0]["repository_name"] == "octryx"
    assert session["change_units"][0]["validation_commands"] == ["npm run lint", "npm run build"]


async def test_coding_sessions_include_latest_agent_chat_session(client, auth_headers, db):
    actor = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    item = _work_item(source_key="OCX-778", title="Expose task chat for coding execution")
    db.add(item)
    await db.flush()
    chat_session = Session(
        user_id=actor.id,
        project_id=None,
        agent_type="coding",
        status="active",
        run_status="running",
        metadata_={},
    )
    db.add(chat_session)
    await db.flush()
    db.add(
        WorkCodingAuditEvent(
            work_item_id=item.id,
            event_type="agent_execution_restarted",
            title="Coding agent execution restarted",
            summary="Restarted from scratch after a declined run.",
            actor_kind="platform",
            evidence_json={
                "session_id": chat_session.id,
                "change_plan_id": "plan-1",
                "restart_from_scratch": True,
                "restart_reason": "PR declined.",
            },
            metadata_json={"source": "unit-test"},
            created_at=utc_now(),
        )
    )
    await db.commit()

    response = await client.get("/api/v1/secure-work/coding-sessions?limit=100", headers=auth_headers)
    assert response.status_code == 200, response.text
    session = next(
        entry
        for entry in response.json()["items"]
        if entry["work_item"]["source_key"] == "OCX-778"
    )
    assert session["agent_sessions"][0]["id"] == chat_session.id
    assert session["agent_sessions"][0]["chat_url"] == f"/chat?session_id={chat_session.id}"
    assert session["agent_sessions"][0]["restart"] is True
    assert session["agent_sessions"][0]["restart_reason"] == "PR declined."


async def test_change_unit_planning_surfaces_missing_profile_fields(client, auth_headers, db):
    incomplete_profile = await _create_profile(
        client,
        auth_headers,
        name="thin-profile",
        service_description="",
        owners=[],
        default_reviewers=[],
        default_branch="",
        required_tests=[],
        build_commands=[],
        test_commands=[],
        lint_commands=[],
        format_commands=[],
        package_commands=[],
        local_run_commands=[],
        important_paths=[],
        protected_paths=[],
        artifact_paths=[],
        test_report_paths=[],
    )
    item = _work_item(source_key="OCX-319", title="Touch poorly profiled repo")
    db.add(item)
    await db.commit()

    response = await client.post(
        f"/api/v1/secure-work/work-items/{item.id}/change-units/plan",
        headers=auth_headers,
        json={"units": [{"repository_profile_id": incomplete_profile["id"], "scope": "Investigate missing metadata"}]},
    )

    assert response.status_code == 200, response.text
    missing = set(response.json()["items"][0]["missing_profile_fields"])
    assert {
        "service_description",
        "owners",
        "default_reviewers",
        "default_branch",
        "build_commands",
        "test_commands",
        "lint_commands",
        "format_commands",
        "package_commands",
        "local_run_commands",
        "important_paths",
        "protected_paths",
        "artifact_paths",
        "test_report_paths",
    } <= missing


def test_branch_suggestion_is_deterministic_and_sanitized():
    item = _work_item(source_key="OCX-77", title="Fix checkout / branch safety!!!")

    assert suggest_branch_name(item, None) == "feature/OCX-77-fix-checkout-branch-safety"
