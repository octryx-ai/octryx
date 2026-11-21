"""Sample payloads for *Send a test alert*, one set per source (automation V3). Invented, generic values."""

from __future__ import annotations

from typing import Any


def _prometheus(status: str, name: str, severity: str, service: str, summary: str) -> dict[str, Any]:
    return {
        "status": status,
        "alerts": [{
            "status": status,
            "labels": {"alertname": name, "severity": severity, "service": service},
            "annotations": {"summary": summary},
            "startsAt": "2026-01-01T10:00:00Z",
            "fingerprint": f"sample-{name.lower()}",
        }],
    }


SAMPLES: dict[str, dict[str, dict[str, Any]]] = {
    "alertmanager": {
        "firing_error_rate": _prometheus("firing", "HighErrorRate", "critical", "sample-api",
                                         "Error rate above 5% for 10 minutes"),
        "firing_disk": _prometheus("firing", "DiskAlmostFull", "warning", "sample-db", "Disk 92% full"),
        "resolved": _prometheus("resolved", "HighErrorRate", "critical", "sample-api", "Error rate back to normal"),
    },
    "grafana": {
        "firing_error_rate": _prometheus("firing", "HighErrorRate", "critical", "sample-api",
                                         "Error rate above 5% for 10 minutes"),
        "firing_disk": _prometheus("firing", "DiskAlmostFull", "warning", "sample-db", "Disk 92% full"),
        "resolved": _prometheus("resolved", "HighErrorRate", "critical", "sample-api", "Error rate back to normal"),
    },
    "datadog": {
        "firing_error_rate": {"title": "High error rate on sample-api", "alert_transition": "Triggered",
                              "priority": "P1", "alert_id": "sample-1", "body": "Error rate above 5%"},
        "firing_disk": {"title": "Disk almost full on sample-db", "alert_transition": "Triggered",
                        "priority": "P2", "alert_id": "sample-2", "body": "Disk 92% full"},
        "resolved": {"title": "High error rate on sample-api", "alert_transition": "Recovered",
                     "priority": "P1", "alert_id": "sample-1"},
    },
    "pagerduty": {
        "firing_error_rate": {"event": {"event_type": "incident.triggered", "data": {
            "id": "SAMPLE1", "title": "High error rate on sample-api", "urgency": "high"}}},
        "firing_disk": {"event": {"event_type": "incident.triggered", "data": {
            "id": "SAMPLE2", "title": "Disk almost full on sample-db", "urgency": "low"}}},
        "resolved": {"event": {"event_type": "incident.resolved", "data": {
            "id": "SAMPLE1", "title": "High error rate on sample-api", "urgency": "high"}}},
    },
    "sentry": {
        "firing_error_rate": {"action": "created", "data": {"issue": {
            "id": "1001", "title": "TimeoutError in sample-api", "level": "error"}}},
        "firing_disk": {"action": "created", "data": {"issue": {
            "id": "1002", "title": "Slow query warning in sample-db", "level": "warning"}}},
        "resolved": {"action": "resolved", "data": {"issue": {
            "id": "1001", "title": "TimeoutError in sample-api", "level": "error"}}},
    },
    "generic": {
        "firing_error_rate": {"title": "High error rate on sample-api", "severity": "critical", "status": "firing",
                              "fingerprint": "sample-1"},
        "firing_disk": {"title": "Disk almost full on sample-db", "severity": "warning", "status": "firing",
                        "fingerprint": "sample-2"},
        "resolved": {"title": "High error rate on sample-api", "severity": "critical", "status": "resolved",
                     "fingerprint": "sample-1"},
    },
    "jira_change": {
        "firing_error_rate": {"key": "SAMPLE-1", "summary": "Checkout fails for some users", "priority": "Highest",
                              "status": "Open", "updated": "2026-01-01T10:00:00Z"},
    },
    "servicenow_change": {
        "firing_error_rate": {"number": "INC0000001", "short_description": "Checkout fails for some users",
                              "priority": "1", "state": "New", "sys_updated_on": "2026-01-01 10:00:00"},
    },
}
SAMPLE_LABELS = {
    "firing_error_rate": "Firing: high error rate (sample)",
    "firing_disk": "Firing: disk almost full (sample)",
    "resolved": "Resolved alert (sample)",
}


def samples_for(source_type: str) -> list[dict[str, str]]:
    return [{"key": key, "label": SAMPLE_LABELS[key]} for key in SAMPLES.get(source_type, SAMPLES["generic"])]


def sample_payload(source_type: str, key: str) -> dict[str, Any] | None:
    return SAMPLES.get(source_type, SAMPLES["generic"]).get(key)


__all__ = ["SAMPLES", "sample_payload", "samples_for"]
