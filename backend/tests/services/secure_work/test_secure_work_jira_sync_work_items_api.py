"""The secure work items API: large boards, Jira metadata filters, role checks, serialization and query previews."""

import pytest
from sqlalchemy import select

from app.models import Permission, Project, Role, User, UserRole, WorkItem
from app.services.auth import hash_password
from app.services.secure_work import build_jira_query_preview
from app.services.secure_work.serializers import serialize_work_item
from tests.jira_intake_support import create_jira_intake, run_jira_intake
from tests.secure_work_jira_sync_support import _issue


async def _login_headers(client, username: str, password: str) -> dict[str, str]:
    response = await client.post("/api/v1/auth/login", data={"username": username, "password": password})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


@pytest.mark.asyncio
async def test_work_items_list_supports_large_project_board(client, auth_headers, db):
    project = (await db.execute(select(Project).where(Project.name == "acme-orders"))).scalar_one()
    create_response = await create_jira_intake(db, {
        "name": "Acme Orders large board",
        "project_id": project.id,
        "filters": {"project_keys": ["OCX"]},
    })
    config_id = create_response["id"]

    await run_jira_intake(db, config_id, {
        "issues": [
            _issue(f"OCX-{index}", summary=f"Large board item {index}")
            for index in range(1, 552)
        ]
    })

    list_response = await client.get(
        f"/api/v1/secure-work/work-items?sync_config_id={config_id}&limit=1000",
        headers=auth_headers,
    )
    assert list_response.status_code == 200, list_response.text
    assert len(list_response.json()["items"]) == 551


@pytest.mark.asyncio
async def test_work_items_list_filters_jira_metadata(client, auth_headers, db):
    project = (await db.execute(select(Project).where(Project.name == "acme-orders"))).scalar_one()
    create_response = await create_jira_intake(db, {
        "name": "Acme Orders metadata board",
        "project_id": project.id,
        "filters": {"project_keys": ["OCX"]},
    })
    config_id = create_response["id"]

    await run_jira_intake(db, config_id, {
        "issues": [
            _issue(
                "OCX-201",
                summary="Release task for the owner",
                labels=["octryx", "backend"],
                fix_versions=["shop_2.4.10"],
                sprint={"id": 901, "name": "Acme Orders Sprint 91", "state": "active"},
            ),
            _issue(
                "OCX-202",
                summary="Release task for Anna",
                assignee="anna",
                assignee_display="Anna Example",
                labels=["frontend"],
                fix_versions=["shop_2.4.11"],
                sprint={"id": 902, "name": "Acme Orders Sprint 92", "state": "future"},
            ),
        ]
    })

    response = await client.get(
        (
            f"/api/v1/secure-work/work-items?sync_config_id={config_id}"
            "&assignee=alice&label=OCTRYX&fix_version=shop_2.4.10&sprint_id=901&limit=1000"
        ),
        headers=auth_headers,
    )
    assert response.status_code == 200, response.text
    items = response.json()["items"]
    assert [item["source_key"] for item in items] == ["OCX-201"]
    assert items[0]["fix_versions"] == ["shop_2.4.10"]
    assert items[0]["sprint"]["name"] == "Acme Orders Sprint 91"

    sprint_name_response = await client.get(
        f"/api/v1/secure-work/work-items?sync_config_id={config_id}&sprint_name=Acme Orders%20Sprint%2092",
        headers=auth_headers,
    )
    assert sprint_name_response.status_code == 200, sprint_name_response.text
    assert [item["source_key"] for item in sprint_name_response.json()["items"]] == ["OCX-202"]


@pytest.mark.asyncio
async def test_secure_work_api_requires_admin_or_operation_role(client, auth_headers, db):
    register_response = await client.post(
        "/api/v1/auth/register",
        headers=auth_headers,
        json={
            "username": "secure-work-viewer",
            "email": "secure-work-viewer@example.test",
            "password": "testpass123",
            "display_name": "Secure Work Viewer",
        },
    )
    assert register_response.status_code == 200, register_response.text
    viewer_headers = await _login_headers(client, "secure-work-viewer", "testpass123")
    denied_response = await client.get("/api/v1/secure-work/coding-sessions", headers=viewer_headers)
    assert denied_response.status_code == 403

    operation_role = (await db.execute(select(Role).where(Role.name == "operation"))).scalar_one_or_none()
    if operation_role is None:
        operation_role = Role(name="operation", description="Can manage operational work intake")
        db.add(operation_role)
        await db.flush()
    db.add(Permission(role_id=operation_role.id, resource="auth", action="login"))
    operation_user = User(
        username="secure-work-operation",
        email="secure-work-operation@example.test",
        password_hash=hash_password("testpass123"),
        display_name="Secure Work Operation",
        account_type="human",
        is_active=True,
    )
    db.add(operation_user)
    await db.flush()
    db.add(UserRole(user_id=operation_user.id, role_id=operation_role.id))
    await db.commit()

    operation_headers = await _login_headers(client, "secure-work-operation", "testpass123")
    allowed_response = await client.get("/api/v1/secure-work/coding-sessions", headers=operation_headers)
    assert allowed_response.status_code == 200, allowed_response.text


@pytest.mark.asyncio
async def test_work_item_serialization_preserves_detail_metadata(db):
    item = WorkItem(
        source_type="jira",
        source_instance="detail-test",
        source_key="OCX-77",
        source_project_key="OCX",
        title="Implement multi-repo guarded code change",
        description="Build a safe development path across two repositories.",
        source_status="In Review",
        priority="High",
        assignee="alice",
        reporter="platform@example.test",
        labels_json=["secure-work", "multi-repo"],
        components_json=["Runtime", "Frontend"],
        fix_versions_json=["2026.06"],
        sprint_json={"id": 42, "name": "Sprint 42"},
        board_json={"id": 7, "name": "Risk Board"},
        linked_issues_json=[{"type": "blocks", "key": "OCX-88"}],
        source_fields_json={
            "acceptance_criteria": "Plan approved, tests pass, reviewers assigned.",
            "affected_repositories": ["octryx-api", "octryx-ui"],
            "planned_branches": ["feature/corp-77-api", "feature/corp-77-ui"],
            "pull_requests": [{"key": "PR-17", "state": "OPEN", "repository": "octryx-ui"}],
            "reviewers": ["Alice Reviewer", "Bob Operator"],
            "raw": {"key": "OCX-77", "fields": {"status": {"name": "In Review"}}},
        },
        work_state="review",
        sync_state="updated",
    )
    db.add(item)
    await db.flush()

    payload = serialize_work_item(item)

    assert payload["source_key"] == "OCX-77"
    assert payload["linked_issues"] == [{"type": "blocks", "key": "OCX-88"}]
    assert payload["source_fields"]["affected_repositories"] == ["octryx-api", "octryx-ui"]
    assert payload["source_fields"]["planned_branches"][1] == "feature/corp-77-ui"
    assert payload["source_fields"]["pull_requests"][0]["key"] == "PR-17"
    assert payload["source_fields"]["reviewers"] == ["Alice Reviewer", "Bob Operator"]
    assert payload["source_fields"]["raw"]["fields"]["status"]["name"] == "In Review"


def test_jira_query_preview_preserves_scoped_filters():
    preview = build_jira_query_preview(
        {
            "project_keys": ["OCX"],
            "labels_include": ["backend"],
            "labels_exclude": ["do-not-sync"],
            "components_include": ["Runtime"],
            "issue_types": ["Story"],
            "statuses": ["In Progress"],
            "assignees": ["alice"],
            "fix_versions": ["2026.06"],
            "sprint_ids": ["42"],
            "sprint_states": ["active"],
            "teams": ["Acme Orders"],
        }
    )

    assert 'project in ("OCX")' in preview
    assert 'labels not in ("do-not-sync")' in preview
    assert 'sprint in ("42")' in preview
    assert 'team in ("Acme Orders")' in preview
    assert preview.endswith("ORDER BY updated DESC")
