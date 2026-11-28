"""Jira, Confluence and knowledge watchers marking source evidence stale."""

from __future__ import annotations

from sqlalchemy import select

from app.models import Project, User, WorkItem
from app.services.engineering_knowledge import upsert_engineering_knowledge_node
from tests.support.connector_watchers_support import _create_watcher


def _jira_issue_payload(
    key: str,
    *,
    status: str = "To Do",
    fix_versions: list[str] | None = None,
    changed_field: str,
) -> dict:
    return {
        "webhookEvent": "jira:issue_updated",
        "actor": {"name": "jira-admin", "displayName": "Jira Admin"},
        "issue": {
            "id": f"id-{key}",
            "key": "OCX-34300",
            "self": "https://jira.example.test/browse/OCX-34300",
            "fields": {
                "project": {"key": "OCX"},
                "summary": "Source evidence watcher coverage",
                "status": {"name": status},
                "fixVersions": [{"name": value} for value in (fix_versions or ["2026.05"])],
            },
        },
        "changelog": {"items": [{"field": changed_field}]},
    }


def _jira_comment_payload() -> dict:
    payload = _jira_issue_payload("comment", changed_field="comment")
    payload["issue_event_type_name"] = "issue_commented"
    payload["comment"] = {
        "id": "c-1",
        "body": "Scope changed: re-check the runbook before continuing.",
        "author": {"name": "reviewer-a", "displayName": "Reviewer A"},
    }
    return payload


def _confluence_page_payload() -> dict:
    return {
        "event_type": "page_updated",
        "actor": {"name": "doc-owner", "displayName": "Doc Owner"},
        "work_item_keys": ["OCX-34300"],
        "page": {
            "id": "100108",
            "title": "OCX-34300 Runtime Runbook",
            "space": {"key": "OCX"},
            "version": {"number": 12},
            "url": "https://confluence.example/display/OCX/Runtime+Runbook",
        },
    }


def _knowledge_document_payload() -> dict:
    return {
        "event_type": "knowledge.updated",
        "actor": "knowledge-sync",
        "work_item_keys": ["OCX-34300"],
        "key": "runtime-runbook",
        "category": "runbooks",
        "title": "OCX-34300 Runtime Runbook",
        "canonical_source": "confluence://OCX/100108",
        "knowledge_layer": "bronze",
    }


async def _seed_work_item_and_graph_node(db):
    project = (await db.execute(select(Project).where(Project.name == "acme-orders"))).scalar_one()
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    item = WorkItem(
        project_id=project.id,
        source_type="jira",
        source_instance="source-watch-test",
        source_key="OCX-34300",
        source_project_key="OCX",
        title="Source evidence watcher coverage",
        source_status="To Do",
        work_state="implementing",
        sync_state="imported",
        fix_versions_json=["2026.05"],
        source_fields_json={
            "confluence_pages": [{"id": "100108", "title": "OCX-34300 Runtime Runbook"}],
            "knowledge_sources": [{"key": "runtime-runbook", "source": "confluence://OCX/100108"}],
        },
    )
    db.add(item)
    graph_node = await upsert_engineering_knowledge_node(
        db,
        node_type="decision",
        node_key="corp-34300-runtime-runbook",
        display_name="OCX-34300 Runtime Runbook",
        summary="Acme Orders runtime runbook evidence derived from Confluence.",
        trust_level="gold",
        source_refs=[{"source_type": "confluence", "source_ref": "confluence://OCX/100108"}],
        created_by_user_id=admin.id,
    )
    await db.commit()
    return item, graph_node


async def _create_source_watchers(client, auth_headers) -> tuple[dict, dict, dict]:
    jira_watcher = await _create_watcher(
        client,
        auth_headers,
        name="Jira source watcher",
        connector_name="jira-cloud",
        connector_instance="acme-orders",
        provider_type="jira",
        event_types=["jira.issue.status_changed", "jira.issue.comment_added", "jira.issue.fix_version_changed"],
        scope={"jira_project_key": "OCX"},
    )
    confluence_watcher = await _create_watcher(
        client,
        auth_headers,
        name="Confluence source watcher",
        connector_name="confluence-wiki",
        connector_instance="acme-orders",
        provider_type="confluence",
        event_types=["confluence.page.updated"],
        scope={"space_key": "OCX"},
    )
    knowledge_watcher = await _create_watcher(
        client,
        auth_headers,
        name="Knowledge source watcher",
        connector_name="knowledge-base",
        connector_instance="global",
        provider_type="knowledge",
        event_types=["knowledge.document.updated"],
        scope={"category": "runbooks"},
    )
    return jira_watcher, confluence_watcher, knowledge_watcher


def _assert_item_and_node_marked_stale(item: WorkItem, graph_node) -> None:
    source_fields = item.source_fields_json
    assert item.work_state == "needs_replan"
    assert graph_node.status == "stale"
    assert graph_node.properties_json["lifecycle"]["source"] == "connector_watcher"
    assert graph_node.properties_json["lifecycle"]["event_ref"]
    assert item.source_status == "In Progress"
    assert item.fix_versions_json == ["2026.06"]
    assert source_fields["source_evidence_stale"] is True
    assert source_fields["requires_replan"] is True
    assert len(source_fields["external_activity"]) == 5
    assert {activity["source"] for activity in source_fields["external_activity"]} >= {
        "jira",
        "confluence",
        "knowledge",
    }
    assert any(activity["event_type"] == "jira.issue.comment_added" for activity in source_fields["external_activity"])
    assert any(activity.get("page", {}).get("id") == "100108" for activity in source_fields["external_activity"])
    assert any(activity.get("document", {}).get("key") == "runtime-runbook" for activity in source_fields["external_activity"])


async def test_jira_confluence_and_knowledge_watchers_mark_source_evidence_stale(client, auth_headers, db):
    item, graph_node = await _seed_work_item_and_graph_node(db)

    jira_watcher, confluence_watcher, knowledge_watcher = await _create_source_watchers(client, auth_headers)

    events = [
        (jira_watcher, _jira_issue_payload("status", status="In Progress", changed_field="status")),
        (jira_watcher, _jira_issue_payload("fix", fix_versions=["2026.06"], changed_field="fixVersion")),
        (jira_watcher, _jira_comment_payload()),
        (confluence_watcher, _confluence_page_payload()),
        (knowledge_watcher, _knowledge_document_payload()),
    ]
    for watcher, payload in events:
        response = await client.post(
            f"/api/v1/connector-watchers/{watcher['id']}/webhook",
            headers={"X-Watcher-Secret": "test-secret"},
            json=payload,
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["processing_result"]["secure_work_link_count"] == 1
        assert body["processing_result"]["secure_work_links"][0]["source_evidence_stale"] is True
        if body["provider_type"] == "confluence":
            lifecycle = body["processing_result"]["engineering_knowledge_lifecycle"]
            assert lifecycle["matched_count"] == 1
            assert graph_node.id in lifecycle["affected_node_ids"]

    await db.refresh(item)
    await db.refresh(graph_node)
    _assert_item_and_node_marked_stale(item, graph_node)

    state_events = await client.get(f"/api/v1/secure-work/work-items/{item.id}/state-events", headers=auth_headers)
    assert state_events.status_code == 200, state_events.text
    event_sources = {event["source"] for event in state_events.json()["items"]}
    assert {"jira_watcher", "confluence_watcher", "knowledge_watcher"} <= event_sources
