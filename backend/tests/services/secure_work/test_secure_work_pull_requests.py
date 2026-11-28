"""The internal pull request record: a workflow run or coding session records the PR it opened for its Work Item
(``pull_requests.sync_pull_request``). There is no user-facing sync, refresh, reviewer, list or backlink route."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.models import AuditLog, Project, User, WorkItem, WorkPullRequest
from app.services.secure_work.pull_requests.pull_requests import sync_pull_request
from app.services.secure_work.pull_requests.record_identity import pull_request_identity
from tests.services.secure_work.repository_record_support import create_repository_record

PR_URL = "https://bitbucket.example.test/projects/OCX/repos/acme-orders-runtime/pull-requests/42"


def _work_item(**overrides) -> WorkItem:
    payload = {
        "source_type": "jira",
        "source_instance": "pr-coordination-test",
        "source_key": "OCX-321",
        "source_project_key": "OCX",
        "title": "Coordinate Bitbucket PRs with Jira work",
        "source_status": "In Progress",
        "work_state": "implementation",
        "sync_state": "imported",
    }
    payload.update(overrides)
    return WorkItem(**payload)


async def _create_repository_profile(client, auth_headers, **overrides) -> dict:
    payload = {
        "name": "acme-orders-runtime",
        "provider": "bitbucket",
        "repository_url": "https://bitbucket.example.test/projects/OCX/repos/acme-orders-runtime",
        "default_branch": "main",
        "jira_project_keys": ["OCX"],
        "owners": ["platform-team"],
        "default_reviewers": ["alice", "bob"],
        "branch_naming_rule": "feature/{key}-{slug}",
        "pr_target_branch": "main",
        "required_pipelines": ["build"],
        "required_tests": ["backend/.venv/bin/python -m pytest backend/tests/services/secure_work/test_secure_work_pull_requests.py"],
        "important_paths": ["backend/app/services/secure_work"],
        "review_status": "reviewed",
    }
    payload.update(overrides)
    return await create_repository_record(payload)  # The record's coding setup, not a Work profile


async def _plan_change_unit(client, auth_headers, item: WorkItem, profile: dict) -> dict:
    response = await client.post(
        f"/api/v1/secure-work/work-items/{item.id}/change-units/plan",
        headers=auth_headers,
        json={
            "units": [
                {
                    "repository_profile_id": profile["id"],
                    "scope": "PR coordination service and UI",
                    "expected_paths": ["backend/app/services/secure_work/pull_requests.py"],
                }
            ]
        },
    )
    assert response.status_code == 200, response.text
    return response.json()["items"][0]


async def test_a_recorded_pr_links_its_item_unit_and_the_units_profile(client, auth_headers, db):
    profile = await _create_repository_profile(client, auth_headers)
    project = Project(name=f"pr-{uuid.uuid4().hex[:6]}", config={})
    db.add(project)
    await db.flush()
    item = _work_item(project_id=project.id)
    db.add(item)
    await db.commit()
    unit = await _plan_change_unit(client, auth_headers, item, profile)
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    payload = {
        "work_item_id": item.id, "change_unit_id": unit["id"], "title": "OCX-321 PR coordination",
        "identity": pull_request_identity("bitbucket", PR_URL, "OCX/acme-orders-runtime", "42"), "pr_url": PR_URL,
        "target_branch": "main", "status": "open", "reviewers": [{"username": "alice"}, {"username": "bob"}],
    }

    created = await sync_pull_request(db, current_user=admin, workspace_id=project.id, payload=payload)
    assert created["created"] is True and created["mismatches"] == []
    assert created["linked_jira_keys"] == ["OCX-321"] and created["repository_profile_id"] == profile["id"]
    assert created["source_branch"] == unit["branch_name"]

    again = await sync_pull_request(db, current_user=admin, workspace_id=project.id,
                                    payload={**payload, "target_branch": "develop", "reviewers": []})
    assert again["created"] is False and again["id"] == created["id"]
    assert {entry["type"] for entry in again["mismatches"]} == {"wrong_target_branch", "missing_reviewer"}
    assert len((await db.execute(select(WorkPullRequest))).scalars().all()) == 1
    audits = (await db.execute(select(AuditLog).where(AuditLog.action == "secure_work.pull_request_synced")))
    assert [audit.details["mismatch_count"] for audit in audits.scalars().all()] == [0, 2]


@pytest.mark.parametrize(("method", "path"), [
    ("POST", "/api/v1/secure-work/pull-requests/sync"),
    ("GET", "/api/v1/secure-work/pull-requests"),
    ("POST", "/api/v1/secure-work/pull-requests/pr-1/refresh"),
    ("POST", "/api/v1/secure-work/pull-requests/pr-1/reviewers"),
    ("GET", "/api/v1/secure-work/work-items/item-1/pull-requests"),
    ("POST", "/api/v1/secure-work/work-items/item-1/pull-requests/backlink-preview"),
])
async def test_the_removed_pull_request_routes_answer_404(client, auth_headers, method, path):
    response = await client.request(method, path, headers=auth_headers, json={})
    assert response.status_code == 404, response.text
