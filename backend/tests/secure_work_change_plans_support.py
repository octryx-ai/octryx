"""Shared helpers for the test_secure_work_change_plans_* modules."""

from __future__ import annotations

from app.models import WorkItem
from tests.repository_record_support import create_repository_record


def _work_item(**overrides) -> WorkItem:
    payload = {
        "source_type": "jira",
        "source_instance": "change-plan-test",
        "source_key": "OCX-320",
        "source_project_key": "OCX",
        "title": "Add approved change plan",
        "description": "Create an auditable planning bridge before code-changing execution.",
        "source_status": "Open",
        "work_state": "intake",
        "sync_state": "imported",
        "labels_json": ["security", "runtime"],
        "components_json": ["Backend"],
        "fix_versions_json": ["2026.06"],
        "assignee": "alice",
        "reporter": "platform@example.test",
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
        "service_description": "Runtime services.",
        "owners": ["alice"],
        "default_reviewers": ["alice"],
        "branch_naming_rule": "feature/{key}-{slug}",
        "test_commands": ["backend/.venv/bin/python -m pytest backend/tests/test_secure_work_change_plans.py"],
        "risk_tags": ["runtime", "security"],
        "important_paths": ["backend/app/services/secure_work"],
        "review_status": "reviewed",
    }
    payload.update(overrides)
    return await create_repository_record(payload)  # The record's coding setup, not a Work profile


async def _create_workflow(client, auth_headers) -> dict:
    response = await client.post(
        "/api/v1/secure-work/workflows",
        headers=auth_headers,
        json={
            "name": "Secure Development",
            "states": [
                {"key": "ready_for_review", "label": "Ready for review"},
                {"key": "approved", "label": "Approved"},
            ],
            "mappings": {
                "approved": {
                    "source_status": "Ready for Development",
                    "source_transition": "Approve plan",
                    "comment_template": "Change Plan approved.",
                    "labels": ["octryx-plan-approved"],
                    "sync_back": True,
                }
            },
            "sync_policy": {"sync_back": True},
            "is_default": True,
            "is_active": True,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


async def _plan_change_unit(client, auth_headers, item: WorkItem, profile: dict) -> dict:
    response = await client.post(
        f"/api/v1/secure-work/work-items/{item.id}/change-units/plan",
        headers=auth_headers,
        json={
            "units": [
                {
                    "repository_profile_id": profile["id"],
                    "scope": "Change Plan service and UI",
                    "expected_paths": ["backend/app/services/secure_work/change_plans.py"],
                }
            ]
        },
    )
    assert response.status_code == 200, response.text
    return response.json()["items"][0]
