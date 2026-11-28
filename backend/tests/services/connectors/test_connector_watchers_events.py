"""Connector watcher event storms, out-of-order events and rule dry runs with event decisions."""

from __future__ import annotations

from tests.support.connector_watchers_support import _create_rule, _create_watcher


async def test_connector_watcher_event_storm_and_out_of_order_are_persisted(client, auth_headers):
    watcher = await _create_watcher(
        client,
        auth_headers,
        webhook={"enabled": True, "rate_limit": {"max_events_per_minute": 2}},
    )

    first = await client.post(
        f"/api/v1/connector-watchers/{watcher['id']}/webhook",
        headers={"X-Watcher-Secret": "test-secret"},
        json={
            "event_type": "jira.issue.updated",
            "external_id": "OCX-345-ORDER-1",
            "actor": "alice",
            "occurred_at": "2026-06-21T10:05:00Z",
        },
    )
    assert first.status_code == 200, first.text
    second = await client.post(
        f"/api/v1/connector-watchers/{watcher['id']}/webhook",
        headers={"X-Watcher-Secret": "test-secret"},
        json={
            "event_type": "jira.issue.updated",
            "external_id": "OCX-345-ORDER-2",
            "actor": "alice",
            "occurred_at": "2026-06-21T10:01:00Z",
        },
    )
    assert second.status_code == 200, second.text
    third = await client.post(
        f"/api/v1/connector-watchers/{watcher['id']}/webhook",
        headers={"X-Watcher-Secret": "test-secret"},
        json={
            "event_type": "jira.issue.updated",
            "external_id": "OCX-345-STORM",
            "actor": "alice",
            "occurred_at": "2026-06-21T10:06:00Z",
        },
    )
    assert third.status_code == 200, third.text
    throttled_event = third.json()
    assert throttled_event["status"] == "rate_limited"
    assert throttled_event["processing_result"]["rate_limited"] is True

    watchers = await client.get("/api/v1/connector-watchers", headers=auth_headers)
    row = next(item for item in watchers.json()["items"] if item["id"] == watcher["id"])
    assert row["status"] == "throttled"
    assert row["health"]["rate_limited_count"] == 1
    assert row["health"]["out_of_order_count"] == 1

    events = await client.get(
        f"/api/v1/connector-watchers/events?watcher_id={watcher['id']}&status=rate_limited",
        headers=auth_headers,
    )
    assert events.status_code == 200, events.text
    assert events.json()["items"][0]["id"] == throttled_event["id"]


async def test_connector_watcher_rules_dry_run_and_event_decisions(client, auth_headers):
    watcher = await _create_watcher(client, auth_headers)
    actions = [
        "audit_only",
        "pause_active_work",
        "ask_agent_replan",
        "request_approval",
        "start_workflow",
    ]
    rules = [
        await _create_rule(
            client,
            auth_headers,
            name=f"Rule {action}",
            actions=[{"type": action, "config": {"workflow_key": "person_research"}}],
            priority=index,
        )
        for index, action in enumerate(actions, start=1)
    ]

    dry_run = await client.post(
        f"/api/v1/connector-watchers/rules/{rules[0]['id']}/test",
        headers=auth_headers,
        json={
            "connector_name": "jira-cloud",
            "connector_instance": "acme-orders",
            "event_type": "jira.issue.updated",
            "actor": "alice",
            "scope": {"project": "OCX"},
        },
    )
    assert dry_run.status_code == 200, dry_run.text
    dry_run_payload = dry_run.json()
    assert dry_run_payload["matched"] is True
    assert dry_run_payload["decision"] == "audit_only"

    event = await client.post(
        f"/api/v1/connector-watchers/{watcher['id']}/webhook",
        headers={"X-Watcher-Secret": "test-secret"},
        json={"event_type": "jira.issue.updated", "external_id": "OCX-4", "actor": "alice"},
    )
    assert event.status_code == 200, event.text
    event_payload = event.json()
    decisions = event_payload["processing_result"]["rule_decisions"]
    assert len(decisions) == len(actions)
    decision_types = {decision["decision"] for decision in decisions}
    assert {
        "audit_only",
        "pause_active_work",
        "ask_agent_replan",
        "request_approval",
        "start_workflow",
    } <= decision_types
    for decision in decisions:
        assert decision["action_results"]
        assert decision["matched"] is True

    decision_list = await client.get("/api/v1/connector-watchers/rule-decisions", headers=auth_headers)
    assert decision_list.status_code == 200, decision_list.text
    assert len(decision_list.json()["items"]) >= len(actions)

    panel_decisions = await client.get(
        "/admin/chat/api/panel/connector-watcher-rule-decisions?limit=10",
        headers=auth_headers,
    )
    assert panel_decisions.status_code == 200, panel_decisions.text
    assert {item["decision"] for item in panel_decisions.json()} >= decision_types
