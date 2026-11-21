from __future__ import annotations

from sqlalchemy import select

from app.models import AuditLog, User, WorkCodingReviewEvent, WorkItem, WorkItemChangeUnit


async def _admin_id(db) -> str:
    return (await db.execute(select(User.id).where(User.username == "admin"))).scalar_one()


async def _seed_review_work_item(db, admin_id):
    item = WorkItem(
        source_type="jira",
        source_instance="review-test",
        source_key="OCX-334",
        source_project_key="OCX",
        title="Review human edit feedback",
        source_status="In Review",
        work_state="review_ready",
        sync_state="imported",
        source_fields_json={
            "requires_replan": True,
            "source_evidence_stale": True,
            "external_activity": [
                {
                    "event_id": "evt-jira-scope",
                    "source": "jira",
                    "event_type": "jira.issue.fix_version_changed",
                    "external_id": "OCX-334",
                    "actor": "Jira Admin",
                    "issue": {"key": "OCX-334", "summary": "Review human edit feedback"},
                    "matched_by": ["jira_issue"],
                    "rule_decisions": [{"decision": "ask_agent_replan", "actions": ["ask_agent_replan"]}],
                    "resulting_actions": ["ask_agent_replan"],
                    "source_evidence_stale": True,
                    "requires_replan": True,
                }
            ],
        },
    )
    db.add(item)
    await db.flush()
    unit = WorkItemChangeUnit(
        work_item_id=item.id,
        repository_name="octryx-api",
        branch_name="feature/corp-334-review-feedback",
        scope="Review controller changes",
        expected_paths_json=["backend/app/services/runtime.py"],
        validation_commands_json=["backend/.venv/bin/python -m pytest backend/tests/test_runtime.py"],
        reviewer_policy_json={"required_roles": ["operation"]},
        created_by=admin_id,
    )
    db.add(unit)
    await db.commit()
    return item, unit


async def _post_comment_and_manual_edit(client, auth_headers, item_id, unit_id):
    comment_response = await client.post(
        f"/api/v1/secure-work/work-items/{item_id}/coding-review-events",
        headers=auth_headers,
        json={
            "change_unit_id": unit_id,
            "event_type": "inline_comment",
            "file_path": "backend/app/services/runtime.py",
            "line_number": 42,
            "severity": "medium",
            "body": "Explain why this branch cannot reuse the legacy fallback.",
            "agent_context": {"constraint": "No hidden runtime fallback is allowed."},
        },
    )
    assert comment_response.status_code == 200, comment_response.text

    edit_response = await client.post(
        f"/api/v1/secure-work/work-items/{item_id}/coding-review-events",
        headers=auth_headers,
        json={
            "change_unit_id": unit_id,
            "event_type": "manual_edit",
            "file_path": "backend/app/services/runtime.py",
            "line_number": 44,
            "body": "Reviewer replaced fallback wording with explicit failure handling.",
            "original_content": "return fallback_result",
            "updated_content": "raise RuntimeError('No approved execution path')",
        },
    )
    assert edit_response.status_code == 200, edit_response.text


async def _assert_cicd_finding_feeds_context(client, auth_headers, item_id):
    finding_response = await client.post(
        f"/api/v1/secure-work/work-items/{item_id}/cicd-findings",
        headers=auth_headers,
        json={
            "event_status": "failed",
            "title": "Unit tests failed",
            "summary": "The coding agent must inspect the failed unit test before continuing.",
            "job_name": "unit-test",
            "commit_sha": "abc123",
        },
    )
    assert finding_response.status_code == 200, finding_response.text
    context_response = await client.get(
        f"/api/v1/secure-work/work-items/{item_id}/agent-feedback-context",
        headers=auth_headers,
    )
    assert context_response.status_code == 200, context_response.text
    assert context_response.json()["cicd_findings_context"]["failure_count"] == 1


async def _assert_review_audit_and_persisted_edit(db, item_id):
    audit = (
        await db.execute(
            select(AuditLog).where(
                AuditLog.resource_id == item_id,
                AuditLog.action == "secure_work.coding_review_event_created",
            )
        )
    ).scalars().all()
    assert len(audit) == 2
    persisted_edit = (
        await db.execute(
            select(WorkCodingReviewEvent).where(
                WorkCodingReviewEvent.work_item_id == item_id,
                WorkCodingReviewEvent.event_type == "manual_edit",
            )
        )
    ).scalar_one()
    assert persisted_edit.updated_content == "raise RuntimeError('No approved execution path')"


async def test_coding_review_events_feed_agent_context_and_audit(client, auth_headers, db):
    admin_id = await _admin_id(db)
    item, unit = await _seed_review_work_item(db, admin_id)

    await _post_comment_and_manual_edit(client, auth_headers, item.id, unit.id)

    events_response = await client.get(
        f"/api/v1/secure-work/work-items/{item.id}/coding-review-events",
        headers=auth_headers,
    )
    assert events_response.status_code == 200, events_response.text
    payload = events_response.json()
    assert len(payload["items"]) == 2
    assert payload["agent_feedback_context"]["counts"] == {"inline_comment": 1, "manual_edit": 1}
    assert payload["agent_feedback_context"]["changed_files"] == ["backend/app/services/runtime.py"]
    assert payload["agent_feedback_context"]["human_edits"][0]["has_updated_content"] is True
    assert "Do not silently revert reviewer changes" in payload["agent_feedback_context"]["agent_instruction"]

    context_response = await client.get(
        f"/api/v1/secure-work/work-items/{item.id}/agent-feedback-context",
        headers=auth_headers,
    )
    assert context_response.status_code == 200, context_response.text
    context = context_response.json()
    assert context["constraints"] == ["No hidden runtime fallback is allowed."]
    assert context["external_activity_context"]["requires_replan_count"] == 1
    assert context["external_activity_context"]["latest_events"][0]["event_type"] == "jira.issue.fix_version_changed"
    assert context["external_activity_context"]["latest_events"][0]["resulting_actions"] == ["ask_agent_replan"]

    await _assert_cicd_finding_feeds_context(client, auth_headers, item.id)

    await _assert_review_audit_and_persisted_edit(db, item.id)
