"""Bitbucket watcher events linking pull request reviews and external changes to work items."""

from __future__ import annotations

from sqlalchemy import select

from app.models import Project, User, WorkItem, WorkItemChangeUnit
from tests.connector_watchers_support import _create_rule, _create_watcher


def _bitbucket_repository() -> dict:
    return {
        "slug": "shop-api",
        "name": "shop-api",
        "project": {"key": "OCX"},
        "links": {"self": [{"href": "https://bitbucket.example/projects/OCX/repos/shop-api"}]},
    }


def _bitbucket_pr_payload(event_key: str, *, actor: str) -> dict:
    return {
        "eventKey": event_key,
        "actor": {"name": actor, "displayName": actor},
        "repository": _bitbucket_repository(),
        "pullRequest": {
            "id": 17,
            "title": "OCX-34200 Agent branch review",
            "state": "OPEN",
            "fromRef": {
                "id": "refs/heads/feature/OCX-34200-agent",
                "displayId": "feature/OCX-34200-agent",
                "repository": _bitbucket_repository(),
            },
            "toRef": {"id": "refs/heads/main", "displayId": "main", "repository": _bitbucket_repository()},
            "links": {
                "self": [
                    {"href": "https://bitbucket.example/projects/OCX/repos/shop-api/pull-requests/17"},
                ]
            },
        },
    }


def _bitbucket_push_payload(*, force_push: bool, actor: str) -> dict:
    change_type = "UPDATE_NON_FAST_FORWARD" if force_push else "UPDATE"
    return {
        "eventKey": "repo:refs_changed",
        "actor": {"name": actor, "displayName": actor},
        "repository": _bitbucket_repository(),
        "force_push": force_push,
        "changes": [
            {
                "refId": "refs/heads/feature/OCX-34200-agent",
                "type": change_type,
                "fromHash": "abc123",
                "toHash": "def456" if not force_push else "fed999",
            }
        ],
        "commits": [
            {
                "hash": "def456" if not force_push else "fed999",
                "message": "OCX-34200 adjust runtime replan handling",
                "author": {"name": actor},
            }
        ],
    }


def _bitbucket_comment_payload(*, actor: str) -> dict:
    payload = _bitbucket_pr_payload("pr:comment:added", actor=actor)
    payload["comment"] = {
        "id": 881,
        "text": "Please re-read the branch before applying more agent changes.",
        "anchor": {"path": "backend/app/services/runtime.py", "line": 42},
    }
    return payload


def _bitbucket_approval_payload(*, actor: str) -> dict:
    payload = _bitbucket_pr_payload("pr:reviewer:approved", actor=actor)
    payload["participant"] = {"user": {"name": actor, "displayName": "Reviewer A"}, "status": "APPROVED"}
    return payload


async def _seed_work_item_and_change_unit(db) -> tuple[WorkItem, WorkItemChangeUnit]:
    project = (await db.execute(select(Project).where(Project.name == "acme-orders"))).scalar_one()
    admin_id = (await db.execute(select(User.id).where(User.username == "admin"))).scalar_one()
    item = WorkItem(
        project_id=project.id,
        source_type="jira",
        source_instance="bitbucket-watch-test",
        source_key="OCX-34200",
        source_project_key="OCX",
        title="Agent branch must react to external Bitbucket events",
        source_status="In Review",
        work_state="implementing",
        sync_state="imported",
        source_fields_json={
            "affected_repositories": ["shop-api"],
            "planned_branches": ["feature/OCX-34200-agent"],
            "pull_requests": [{"id": "17", "url": "https://bitbucket.example/projects/OCX/repos/shop-api/pull-requests/17"}],
        },
    )
    db.add(item)
    await db.flush()
    unit = WorkItemChangeUnit(
        work_item_id=item.id,
        repository_name="shop-api",
        branch_name="feature/OCX-34200-agent",
        pr_link="https://bitbucket.example/projects/OCX/repos/shop-api/pull-requests/17",
        scope="Update agent runtime",
        expected_paths_json=["backend/app/services/runtime.py"],
        validation_commands_json=["backend/.venv/bin/python -m pytest backend/tests/test_runtime.py"],
        created_by=admin_id,
    )
    db.add(unit)
    await db.commit()
    return item, unit


async def _create_bitbucket_watcher_and_replan_rule(client, auth_headers) -> dict:
    watcher = await _create_watcher(
        client,
        auth_headers,
        name="Bitbucket reviewer watcher",
        connector_name="bitbucket-main",
        connector_instance="acme-orders",
        provider_type="bitbucket",
        event_types=[
            "bitbucket.pull_request.updated",
            "bitbucket.commit.pushed",
            "bitbucket.commit.force_pushed",
            "bitbucket.pull_request.comment_added",
            "bitbucket.pull_request.approved",
        ],
        scope={"bitbucket_project_key": "OCX", "repository_slug": "shop-api"},
    )
    await _create_rule(
        client,
        auth_headers,
        name="Bitbucket human force push requires replan",
        connector_name="bitbucket-main",
        event_types=["bitbucket.commit.force_pushed"],
        conditions={"all": []},
        actions=[{"type": "ask_agent_replan"}],
        priority=1,
    )
    return watcher


async def _post_watcher_payloads(client, watcher: dict, payloads: list[dict]) -> list[dict]:
    responses = []
    for payload in payloads:
        response = await client.post(
            f"/api/v1/connector-watchers/{watcher['id']}/webhook",
            headers={"X-Watcher-Secret": "test-secret"},
            json=payload,
        )
        assert response.status_code == 200, response.text
        responses.append(response.json())
    return responses


def _assert_item_needs_replan(item: WorkItem, unit: WorkItemChangeUnit) -> None:
    source_fields = item.source_fields_json
    activities = source_fields["external_activity"]
    assert len(activities) == 5
    assert item.work_state == "needs_replan"
    assert source_fields["externally_modified"] is True
    assert source_fields["requires_replan"] is True
    assert source_fields["external_replan_reason"]["event_type"] == "bitbucket.commit.force_pushed"
    assert activities[0]["event_type"] == "bitbucket.commit.force_pushed"
    assert activities[0]["rule_decisions"][0]["decision"] == "ask_agent_replan"
    assert "ask_agent_replan" in activities[0]["resulting_actions"]
    assert any(activity["event_type"] == "bitbucket.pull_request.comment_added" for activity in activities)
    assert any(activity.get("reviewer", {}).get("name") == "reviewer-a" for activity in activities)
    assert all(unit.id in activity["change_unit_ids"] for activity in activities)


async def test_bitbucket_watcher_links_review_and_external_change_events(client, auth_headers, db):
    item, unit = await _seed_work_item_and_change_unit(db)

    watcher = await _create_bitbucket_watcher_and_replan_rule(client, auth_headers)

    payloads = [
        _bitbucket_pr_payload("pr:modified", actor="alice"),
        _bitbucket_push_payload(force_push=False, actor="alice"),
        _bitbucket_comment_payload(actor="reviewer-a"),
        _bitbucket_approval_payload(actor="reviewer-a"),
        _bitbucket_push_payload(force_push=True, actor="alice"),
    ]
    responses = await _post_watcher_payloads(client, watcher, payloads)

    event_types = {response["event_type"] for response in responses}
    assert {
        "bitbucket.pull_request.updated",
        "bitbucket.commit.pushed",
        "bitbucket.pull_request.comment_added",
        "bitbucket.pull_request.approved",
        "bitbucket.commit.force_pushed",
    } <= event_types
    for response in responses:
        assert response["processing_result"]["secure_work_link_count"] == 1
        assert response["processing_result"]["secure_work_links"][0]["source_key"] == "OCX-34200"

    await db.refresh(item)
    _assert_item_needs_replan(item, unit)

    state_events = await client.get(f"/api/v1/secure-work/work-items/{item.id}/state-events", headers=auth_headers)
    assert state_events.status_code == 200, state_events.text
    bitbucket_state_events = [event for event in state_events.json()["items"] if event["source"] == "bitbucket_watcher"]
    assert bitbucket_state_events
    assert any(event["to_state"] == "needs_replan" for event in bitbucket_state_events)
    assert any(event["conflict"]["resulting_actions"] == ["ask_agent_replan"] for event in bitbucket_state_events)

    panel_events = await client.get("/admin/chat/api/panel/connector-watcher-events?limit=10", headers=auth_headers)
    assert panel_events.status_code == 200, panel_events.text
    bitbucket_rows = [row for row in panel_events.json() if row["provider_type"] == "bitbucket"]
    assert any(row["normalized"]["bitbucket"]["branch"] == "feature/OCX-34200-agent" for row in bitbucket_rows)
