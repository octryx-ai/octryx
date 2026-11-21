"""Connector watcher webhook secrets and deduplication, polling cursors, unavailable polling triggers and retry with dead letters."""

from __future__ import annotations

from tests.connector_watchers_support import _create_watcher, _watcher_payload


async def test_connector_watcher_webhook_secret_deduplicates_and_surfaces_in_panel(client, auth_headers):
    watcher = await _create_watcher(client, auth_headers)

    denied = await client.post(
        f"/api/v1/connector-watchers/{watcher['id']}/webhook",
        headers={"X-Watcher-Secret": "wrong"},
        json={"event_type": "jira.issue.updated", "external_id": "OCX-1", "actor": "alice"},
    )
    assert denied.status_code == 401

    first = await client.post(
        f"/api/v1/connector-watchers/{watcher['id']}/webhook",
        headers={"X-Watcher-Secret": "test-secret"},
        json={"event_type": "jira.issue.updated", "external_id": "OCX-1", "actor": "alice"},
    )
    assert first.status_code == 200, first.text
    first_event = first.json()
    assert first_event["status"] == "received"
    assert first_event["normalized"]["provider"] == "jira"
    assert first_event["actor"] == "alice"

    duplicate = await client.post(
        f"/api/v1/connector-watchers/{watcher['id']}/webhook",
        headers={"X-Watcher-Secret": "test-secret"},
        json={"event_type": "jira.issue.updated", "external_id": "OCX-1", "actor": "alice"},
    )
    assert duplicate.status_code == 200, duplicate.text
    duplicate_event = duplicate.json()
    assert duplicate_event["status"] == "duplicate"
    assert duplicate_event["duplicate_of_event_id"] == first_event["id"]

    panel_watchers = await client.get("/admin/chat/api/panel/connector-watchers", headers=auth_headers)
    assert panel_watchers.status_code == 200, panel_watchers.text
    panel_watcher = panel_watchers.json()[0]
    assert panel_watcher["last_event_id"] == duplicate_event["id"]
    assert panel_watcher["secret_configured"] is True
    assert panel_watcher["health"]["last_event_status"] == "duplicate"

    panel_events = await client.get("/admin/chat/api/panel/connector-watcher-events?limit=10", headers=auth_headers)
    assert panel_events.status_code == 200, panel_events.text
    statuses = {event["status"] for event in panel_events.json()}
    assert {"received", "duplicate"} <= statuses


async def test_connector_watcher_polling_updates_cursor_and_records_events(client, auth_headers):
    watcher = await _create_watcher(client, auth_headers)
    assert watcher["polling"]["trigger_owner"] == "api_ingestion"
    assert watcher["polling_contract"]["trigger_owner"] == "api_ingestion"
    assert watcher["polling_contract"]["background_worker"] is False
    assert watcher["polling_contract"]["provider_fetcher"] is False
    assert watcher["polling_contract"]["ingest_endpoint"] == "/api/v1/connector-watchers/{watcher_id}/poll"

    response = await client.post(
        f"/api/v1/connector-watchers/{watcher['id']}/poll",
        headers=auth_headers,
        json={
            "cursor": {"since": "2026-06-21T10:00:00Z", "page": 2},
            "events": [
                {
                    "event_type": "jira.issue.transitioned",
                    "external_id": "OCX-2",
                    "actor": "bob",
                    "scope": {"project": "OCX"},
                }
            ],
        },
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["count"] == 1
    assert payload["items"][0]["normalized"]["source"] == "polling"
    assert payload["watcher"]["cursor"] == {"since": "2026-06-21T10:00:00Z", "page": 2}
    assert '"page": 2' in payload["watcher"]["last_cursor"]
    assert payload["watcher"]["polling_contract"]["cursor_owner"] == "poll_ingestion_caller"

    panel_watchers = await client.get("/admin/chat/api/panel/connector-watchers", headers=auth_headers)
    assert panel_watchers.status_code == 200, panel_watchers.text
    panel_watcher = next(item for item in panel_watchers.json() if item["id"] == watcher["id"])
    assert panel_watcher["polling_contract"]["supported"] is True
    assert panel_watcher["polling_contract"]["background_worker"] is False


async def test_connector_watcher_rejects_unavailable_background_polling_trigger(client, auth_headers):
    response = await client.post(
        "/api/v1/connector-watchers",
        headers=auth_headers,
        json=_watcher_payload(
            mode="polling",
            polling={"enabled": True, "trigger_owner": "background_worker", "interval_seconds": 300},
            webhook={"enabled": False},
        ),
    )
    assert response.status_code == 422, response.text
    assert "trigger_owner=api_ingestion" in response.json()["detail"]
    assert "provider-owned fetch adapter" in response.json()["detail"]


async def test_connector_watcher_polling_failure_retry_dead_letters_event(client, auth_headers):
    watcher = await _create_watcher(
        client,
        auth_headers,
        mode="polling",
        polling={"enabled": True, "trigger_owner": "api_ingestion", "interval_seconds": 300},
        webhook={"enabled": False},
        retry_policy={"max_attempts": 2, "retry_delay_seconds": 1},
    )

    failed = await client.post(
        f"/api/v1/connector-watchers/{watcher['id']}/poll",
        headers=auth_headers,
        json={
            "events": [
                {
                    "event_type": "jira.issue.updated",
                    "external_id": "OCX-POLL-RETRY",
                    "actor": "poller",
                    "_simulate_processing_error": True,
                }
            ],
        },
    )
    assert failed.status_code == 200, failed.text
    failed_event = failed.json()["items"][0]
    assert failed_event["status"] == "failed"
    assert failed_event["attempts"] == 1
    assert failed_event["next_retry_at"] is not None
    assert failed_event["normalized"]["source"] == "polling"

    retry = await client.post(
        f"/api/v1/connector-watchers/events/{failed_event['id']}/retry",
        headers=auth_headers,
    )
    assert retry.status_code == 200, retry.text
    retried_event = retry.json()
    assert retried_event["status"] == "dead_letter"
    assert retried_event["attempts"] == 2

    watchers = await client.get("/api/v1/connector-watchers", headers=auth_headers)
    assert watchers.status_code == 200, watchers.text
    row = next(item for item in watchers.json()["items"] if item["id"] == watcher["id"])
    assert row["status"] == "degraded"
    assert row["dead_letter_count"] == 1


async def test_connector_watcher_retry_dead_letters_failed_event(client, auth_headers):
    watcher = await _create_watcher(client, auth_headers)

    failed = await client.post(
        f"/api/v1/connector-watchers/{watcher['id']}/webhook",
        headers={"X-Watcher-Secret": "test-secret"},
        json={
            "event_type": "jira.issue.updated",
            "external_id": "OCX-3",
            "actor": "ci",
            "_simulate_processing_error": True,
        },
    )
    assert failed.status_code == 200, failed.text
    failed_event = failed.json()
    assert failed_event["status"] == "failed"
    assert failed_event["attempts"] == 1
    assert failed_event["next_retry_at"] is not None

    retry = await client.post(
        f"/api/v1/connector-watchers/events/{failed_event['id']}/retry",
        headers=auth_headers,
    )
    assert retry.status_code == 200, retry.text
    retried_event = retry.json()
    assert retried_event["status"] == "dead_letter"
    assert retried_event["attempts"] == 2

    watchers = await client.get("/api/v1/connector-watchers", headers=auth_headers)
    assert watchers.status_code == 200, watchers.text
    row = next(item for item in watchers.json()["items"] if item["id"] == watcher["id"])
    assert row["status"] == "degraded"
    assert row["dead_letter_count"] == 1


async def test_connector_watcher_retry_can_replay_transient_failure(client, auth_headers):
    watcher = await _create_watcher(client, auth_headers)

    failed = await client.post(
        f"/api/v1/connector-watchers/{watcher['id']}/webhook",
        headers={"X-Watcher-Secret": "test-secret"},
        json={
            "event_type": "jira.issue.updated",
            "external_id": "OCX-345-RETRY",
            "actor": "ci",
            "_simulate_processing_error": True,
            "_simulate_retry_success": True,
        },
    )
    assert failed.status_code == 200, failed.text
    failed_event = failed.json()
    assert failed_event["status"] == "failed"

    replay = await client.post(
        f"/api/v1/connector-watchers/events/{failed_event['id']}/replay",
        headers=auth_headers,
    )
    assert replay.status_code == 200, replay.text
    replayed_event = replay.json()
    assert replayed_event["status"] == "processed"
    assert replayed_event["attempts"] == 2
    assert replayed_event["processing_result"]["replay"]["status"] == "processed"

    watchers = await client.get("/api/v1/connector-watchers", headers=auth_headers)
    row = next(item for item in watchers.json()["items"] if item["id"] == watcher["id"])
    assert row["health"]["retry_count"] == 1
    assert row["health"]["replay_count"] == 1
