"""Shared helpers for the test_connector_watchers_* modules."""

from __future__ import annotations


def _watcher_payload(**overrides) -> dict:
    payload = {
        "name": "Mock Jira watcher",
        "connector_name": "jira-cloud",
        "connector_instance": "acme-orders",
        "provider_type": "jira",
        "mode": "hybrid",
        "event_types": ["jira.issue.updated"],
        "scope": {"project": "OCX"},
        "webhook": {"enabled": True},
        "polling": {"enabled": True, "interval_seconds": 300},
        "retry_policy": {"max_attempts": 2, "retry_delay_seconds": 1},
        "webhook_secret": "test-secret",
        "is_active": True,
    }
    payload.update(overrides)
    return payload


async def _create_watcher(client, auth_headers, **overrides) -> dict:
    response = await client.post(
        "/api/v1/connector-watchers",
        headers=auth_headers,
        json=_watcher_payload(**overrides),
    )
    assert response.status_code == 200, response.text
    return response.json()


async def _create_rule(client, auth_headers, **overrides) -> dict:
    payload = {
        "name": "Audit Jira updates",
        "connector_name": "jira-cloud",
        "event_types": ["jira.issue.updated"],
        "conditions": {"all": [{"field": "actor", "operator": "equals", "value": "alice"}]},
        "actions": [{"type": "audit_only"}],
        "priority": 100,
        "status": "published",
        "is_active": True,
    }
    payload.update(overrides)
    response = await client.post("/api/v1/connector-watchers/rules", headers=auth_headers, json=payload)
    assert response.status_code == 200, response.text
    return response.json()
