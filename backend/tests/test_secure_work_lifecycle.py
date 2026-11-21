from __future__ import annotations

from sqlalchemy import select

from app.models import Project, Session, User, WorkCodingAuditEvent, WorkItem, WorkItemChangeUnit, WorkPullRequest
from app.time_utils import utc_now


async def test_work_item_lifecycle_links_work_coding_chat_jira_branch_and_pr(client, auth_headers, db):
    actor = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    project = Project(name="lifecycle-workspace", config={})
    db.add(project)
    await db.flush()
    item = WorkItem(
        project_id=project.id,
        source_type="jira",
        source_instance="risk",
        source_key="ACME-615",
        source_project_key="ACME",
        source_url="https://jira.example.test/browse/ACME-615",
        title="Cleaning Terraform and Helm Config",
        source_status="In Progress",
        work_state="implementation",
        sync_state="imported",
        labels_json=["octryx"],
    )
    db.add(item)
    await db.flush()
    unit = WorkItemChangeUnit(
        work_item_id=item.id,
        repository_name="aws-shop-infrastructure",
        branch_name="feature/ACME-615-clean-pipeline",
        expected_paths_json=["removed.txt", "config/prod.json"],
        validation_commands_json=["terraform validate"],
        created_by=actor.id,
        updated_by=actor.id,
    )
    db.add(unit)
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
            event_type="agent_execution_started",
            title="Coding agent execution started",
            actor_kind="platform",
            evidence_json={"session_id": chat_session.id, "change_plan_id": "plan-1"},
            metadata_json={"source": "unit-test"},
            created_at=utc_now(),
        )
    )
    db.add(
        WorkPullRequest(
            work_item_id=item.id,
            scope_key=item.project_id,
            change_unit_id=unit.id,
            provider="bitbucket",
            provider_instance="bitbucket.example.test",
            project_key="SHOP",
            repository_slug="aws-shop-infrastructure",
            repository_url="https://bitbucket.example.test/projects/SHOP/repos/aws-shop-infrastructure",
            pr_id="42",
            pr_key="SHOP/aws-shop-infrastructure#42",
            pr_url="https://bitbucket.example.test/projects/SHOP/repos/aws-shop-infrastructure/pull-requests/42",
            title="ACME-615 clean pipeline",
            source_branch="feature/ACME-615-clean-pipeline",
            target_branch="master",
            status="open",
            created_by=actor.id,
            updated_by=actor.id,
        )
    )
    await db.commit()

    response = await client.get(f"/api/v1/secure-work/work-items/{item.id}/lifecycle", headers=auth_headers)

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["work_item"]["source_key"] == "ACME-615"
    assert payload["links"]["jira_url"] == "https://jira.example.test/browse/ACME-615"
    assert payload["links"]["coding_url"] == f"/chat?area=coding&work_item_id={item.id}"
    assert payload["links"]["active_chat_url"] == f"/chat?session_id={chat_session.id}"
    assert payload["active_agent_session"]["id"] == chat_session.id
    assert payload["branches"][0]["branch_name"] == "feature/ACME-615-clean-pipeline"
    assert payload["branches"][0]["pull_request_url"].endswith("/pull-requests/42")
    assert payload["pull_requests"][0]["pr_url"].endswith("/pull-requests/42")
