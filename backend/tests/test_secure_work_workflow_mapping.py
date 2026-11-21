from __future__ import annotations

from sqlalchemy import select

from app.models import AuditLog, WorkItem, WorkItemStateEvent
from app.time_utils import utc_now


def _workflow_payload() -> dict:
    return {
        "name": "Secure development workflow",
        "description": "Team-configurable workflow for safe code changes.",
        "is_default": True,
        "states": [
            {"key": "intake", "label": "Intake"},
            {"key": "clarification", "label": "Clarification"},
            {"key": "ready_for_development", "label": "Ready for development"},
        ],
        "mappings": {
            "clarification": {
                "source_status": "Clarification",
                "source_transition": "Request clarification",
                "comment_template": "Octryx needs clarification before implementation.",
                "labels": ["octryx-clarification"],
                "custom_fields": {"customfield_12345": "needs-clarification"},
                "sync_back": True,
            },
            "ready_for_development": {
                "source_status": "Ready for Development",
                "source_transition": "Approve for development",
                "labels": ["octryx-ready"],
                "sync_back": True,
            },
        },
    }


def _work_item(**overrides) -> WorkItem:
    payload = {
        "source_type": "jira",
        "source_instance": "workflow-test",
        "source_key": "OCX-317",
        "source_project_key": "OCX",
        "title": "Configure workflow state mapping",
        "source_status": "Open",
        "work_state": "intake",
        "sync_state": "imported",
        "last_source_updated_at": utc_now(),
    }
    payload.update(overrides)
    return WorkItem(**payload)


async def _confirmed(client, auth_headers, workflow_id: str, item_id: str, to_state: str, **extra) -> str:
    """An apply sends the effects hash of the preview it confirmed."""
    dry = await client.post(f"/api/v1/secure-work/workflows/{workflow_id}/dry-run-transition", headers=auth_headers,
                            json={"work_item_id": item_id, "to_state": to_state, **extra})
    assert dry.status_code == 200, dry.text
    return dry.json()["preview"]["jira_sync_preview"]["effects_hash"]


async def _create_workflow(client, auth_headers) -> dict:
    response = await client.post("/api/v1/secure-work/workflows", headers=auth_headers, json=_workflow_payload())
    assert response.status_code == 200, response.text
    return response.json()


async def test_workflow_mapping_dry_run_shows_jira_intent_without_mutating_item(client, auth_headers, db):
    workflow = await _create_workflow(client, auth_headers)
    item = _work_item()
    db.add(item)
    await db.commit()

    response = await client.post(
        f"/api/v1/secure-work/workflows/{workflow['id']}/dry-run-transition",
        headers=auth_headers,
        json={
            "work_item_id": item.id,
            "to_state": "clarification",
            "reason": "Acceptance criteria are incomplete.",
            "source": "operator",
        },
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    preview = payload["preview"]
    assert preview["from_state"] == "intake"
    assert preview["to_state"] == "clarification"
    assert preview["jira_sync_preview"]["will_mutate_jira"] is False
    assert preview["jira_sync_preview"]["sync_back"] is True
    assert preview["jira_sync_preview"]["transition"] == "Request clarification"
    assert preview["jira_sync_preview"]["target_status"] == "Clarification"
    assert preview["jira_sync_preview"]["labels"] == ["octryx-clarification"]
    assert preview["jira_sync_preview"]["custom_fields"] == {"customfield_12345": "needs-clarification"}
    assert payload["event"]["dry_run"] is True

    persisted = await db.get(WorkItem, item.id)
    assert persisted is not None
    assert persisted.work_state == "intake"
    event_count = (
        await db.execute(select(WorkItemStateEvent).where(WorkItemStateEvent.work_item_id == item.id))
    ).scalars().all()
    assert len(event_count) == 1


async def test_workflow_transition_updates_state_and_writes_audit(client, auth_headers, db):
    workflow = await _create_workflow(client, auth_headers)
    item = _work_item(source_key="OCX-318")
    db.add(item)
    await db.commit()

    response = await client.post(
        f"/api/v1/secure-work/work-items/{item.id}/transition",
        headers=auth_headers,
        json={
            "workflow_id": workflow["id"],
            "to_state": "ready_for_development",
            "reason": "Plan approved by operator.",
            "source": "operator",
            "effects_hash": await _confirmed(client, auth_headers, workflow["id"], item.id, "ready_for_development"),
        },
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["work_state"] == "ready_for_development"
    assert payload["event"]["dry_run"] is False
    assert payload["event"]["reason"] == "Plan approved by operator."

    persisted = await db.get(WorkItem, item.id)
    assert persisted is not None
    assert persisted.work_state == "ready_for_development"
    audit = (
        await db.execute(
            select(AuditLog).where(
                AuditLog.resource_type == "work_item",
                AuditLog.resource_id == item.id,
                AuditLog.action == "secure_work.transition_applied",
            )
        )
    ).scalar_one()
    assert audit.details["to_state"] == "ready_for_development"
    assert audit.details["jira_sync_preview"]["transition"] == "Approve for development"


async def test_workflow_transition_conflict_requires_explicit_override(client, auth_headers, db):
    workflow = await _create_workflow(client, auth_headers)
    item = _work_item(source_key="OCX-319", last_source_updated_at=utc_now())
    db.add(item)
    await db.commit()

    conflict_response = await client.post(
        f"/api/v1/secure-work/work-items/{item.id}/transition",
        headers=auth_headers,
        json={
            "workflow_id": workflow["id"],
            "to_state": "clarification",
            "reason": "External Jira update should be reviewed first.",
            "source_jira_updated_at": "2999-01-01T00:00:00Z",
            "effects_hash": await _confirmed(client, auth_headers, workflow["id"], item.id, "clarification"),
        },
    )

    assert conflict_response.status_code == 409, conflict_response.text
    assert "Jira changed" in str(conflict_response.json()["detail"]), "the conflict, not a stale preview"
    persisted = await db.get(WorkItem, item.id)
    assert persisted is not None
    assert persisted.work_state == "intake"

    override_response = await client.post(
        f"/api/v1/secure-work/work-items/{item.id}/transition",
        headers=auth_headers,
        json={
            "workflow_id": workflow["id"],
            "to_state": "clarification",
            "reason": "Operator reviewed the Jira delta.",
            "source_jira_updated_at": "2999-01-01T00:00:00Z",
            "allow_conflict": True,
            "effects_hash": await _confirmed(client, auth_headers, workflow["id"], item.id, "clarification"),
        },
    )

    assert override_response.status_code == 200, override_response.text
    assert override_response.json()["preview"]["conflict"]["has_conflict"] is True


async def test_workflow_event_history_is_returned_for_work_item(client, auth_headers, db):
    workflow = await _create_workflow(client, auth_headers)
    item = _work_item(source_key="OCX-320")
    db.add(item)
    await db.commit()
    transition = await client.post(
        f"/api/v1/secure-work/work-items/{item.id}/transition",
        headers=auth_headers,
        json={"workflow_id": workflow["id"], "to_state": "clarification", "reason": "Need owner decision.",
              "effects_hash": await _confirmed(client, auth_headers, workflow["id"], item.id, "clarification")},
    )
    assert transition.status_code == 200, transition.text

    response = await client.get(f"/api/v1/secure-work/work-items/{item.id}/state-events", headers=auth_headers)

    assert response.status_code == 200, response.text
    # The confirmed dry-run is an event too; one transition was applied.
    events = [event for event in response.json()["items"] if not event["dry_run"]]
    assert len(events) == 1
    assert events[0]["from_state"] == "intake"
    assert events[0]["to_state"] == "clarification"
    assert events[0]["jira_sync_preview"]["comment_template"].startswith("Octryx needs clarification")
