"""``normalize_alert`` keeps an alert's start, end, occurrences, common labels and annotations, bounded."""

from __future__ import annotations

import hashlib
import json

from app.services.inbound_alerts.normalize import (
    MAX_OCCURRENCES,
    NormalizedAlert,
    normalize_alert,
    parse_instant,
)
from app.services.inbound_alerts.samples import sample_payload

# An Alertmanager v0.34 webhook body (``version: "4"``) as it sends a group of two firing alerts and a resolved one:
# nanosecond startsAt, Go's zero time as the end of a firing alert.
ALERTMANAGER_V034 = {
    "receiver": "octryx-s5", "status": "firing", "version": "4", "truncatedAlerts": 0,
    "groupKey": '{}:{alertname="InstanceDown", service="octryx-s5-canary"}',
    "groupLabels": {"alertname": "InstanceDown", "service": "octryx-s5-canary"},
    "commonLabels": {"alertname": "InstanceDown", "job": "octryx-s5-canary", "service": "octryx-s5-canary",
                     "severity": "warning"},
    "commonAnnotations": {"summary": "The canary is down"},
    "externalURL": "http://alertmanager:9093",
    "alerts": [
        {"status": "firing", "labels": {"alertname": "InstanceDown", "instance": "canary-b:80", "job": "octryx-s5-canary",
                                         "service": "octryx-s5-canary", "severity": "warning"},
         "annotations": {"summary": "The canary is down"}, "startsAt": "2026-10-15T10:01:30.512345678Z",
         "endsAt": "0001-01-01T00:00:00Z", "generatorURL": "http://prometheus:9090/graph?g0.expr=up",
         "fingerprint": "b2c3d4e5f6a70819"},
        {"status": "firing", "labels": {"alertname": "InstanceDown", "instance": "canary-a:80", "job": "octryx-s5-canary",
                                         "service": "octryx-s5-canary", "severity": "warning"},
         "annotations": {"summary": "The canary is down"}, "startsAt": "2026-10-15T10:00:00.000000001Z",
         "endsAt": "0001-01-01T00:00:00Z", "generatorURL": "http://prometheus:9090/graph?g0.expr=up",
         "fingerprint": "a1b2c3d4e5f60718"},
        {"status": "resolved", "labels": {"alertname": "InstanceDown", "instance": "canary-c:80",
                                           "job": "octryx-s5-canary", "service": "octryx-s5-canary", "severity": "warning"},
         "annotations": {"summary": "The canary is down"}, "startsAt": "2026-10-15T09:00:00Z",
         "endsAt": "2026-10-15T09:30:00Z", "fingerprint": "c3d4e5f6a7081920"},
    ],
}


def test_an_alertmanager_v034_group_keeps_its_occurrences_start_and_common_labels():
    alert = normalize_alert("alertmanager", ALERTMANAGER_V034)

    assert alert.status == "firing"
    assert alert.starts_at == "2026-10-15T10:00:00Z", "the earliest startsAt of the shown (firing) alerts"
    assert alert.ends_at == "", "a firing group has no end (Go's zero time is no instant)"
    assert alert.occurrences == (("a1b2c3d4e5f60718", "2026-10-15T10:00:00Z"),
                                 ("b2c3d4e5f6a70819", "2026-10-15T10:01:30.512345Z"))
    assert alert.common_labels == ALERTMANAGER_V034["commonLabels"]
    assert alert.annotations == {"summary": "The canary is down"}
    assert alert.title == "InstanceDown · octryx-s5-canary (+1 more)"
    assert alert.labels["instance"] == "canary-b:80", "labels stay the first shown alert's (unchanged)"


def test_the_group_fingerprint_hashes_the_shown_alerts():
    # Still sha256(source, sorted fingerprints of the shown alerts): stored events and their grouping stay valid.
    alert = normalize_alert("alertmanager", ALERTMANAGER_V034)

    expected = hashlib.sha256(json.dumps(["alertmanager", ["a1b2c3d4e5f60718", "b2c3d4e5f6a70819"]],
                                         sort_keys=True).encode()).hexdigest()
    assert alert.fingerprint == expected


def test_a_resolved_group_has_its_latest_end():
    payload = {**ALERTMANAGER_V034, "status": "resolved",
               "alerts": [{**item, "status": "resolved", "endsAt": end}
                          for item, end in zip(ALERTMANAGER_V034["alerts"][:2],
                                               ("2026-10-15T10:20:00Z", "2026-10-15T10:25:00+02:00"), strict=True)]}
    alert = normalize_alert("alertmanager", payload)

    assert alert.status == "resolved"
    assert alert.ends_at == "2026-10-15T10:20:00Z", "10:25+02:00 is 08:25Z: the latest end is 10:20Z"
    assert len(alert.occurrences) == 2, "a resolved alert keeps its occurrence pairs (S6 matches them)"


def test_without_common_labels_the_first_alerts_labels_are_used():
    alert = normalize_alert("alertmanager", sample_payload("alertmanager", "firing_error_rate"))

    assert alert.common_labels == {"alertname": "HighErrorRate", "severity": "critical", "service": "sample-api"}
    assert alert.starts_at == "2026-01-01T10:00:00Z"
    assert alert.occurrences == (("sample-higherrorrate", "2026-01-01T10:00:00Z"),)
    assert alert.annotations == {"summary": "Error rate above 5% for 10 minutes"}


def test_labels_and_annotations_are_bounded_and_never_cut_to_an_equal_value():
    many = {f"k{index:02d}": "v" for index in range(60)}
    long_value = "shop" + "x" * 200
    payload = {"status": "firing", "commonLabels": {**many, "namespace": long_value, "spaced": "shop "},
               "commonAnnotations": {"description": "d" * 2000},
               "alerts": [{"status": "firing", "labels": {"alertname": "A"}, "startsAt": "2026-10-15T10:00:00Z",
                           "fingerprint": f"f{index}"} for index in range(80)]}
    alert = normalize_alert("grafana", payload)

    assert len(alert.common_labels) == 40
    assert all(len(value) <= 120 for value in alert.common_labels.values())
    assert len(alert.annotations["description"]) == 500
    assert len(alert.occurrences) == MAX_OCCURRENCES
    many_namespace = normalize_alert("grafana", {**payload, "commonLabels": {"namespace": long_value,
                                                                             "spaced": "shop "}})
    assert many_namespace.common_labels["namespace"].endswith("…")
    assert many_namespace.common_labels["namespace"] != long_value[:120]
    assert many_namespace.common_labels["spaced"] == "shop ", "values are not stripped: matching is exact"


def test_other_sources_have_no_occurrences():
    for source in ("datadog", "pagerduty", "sentry", "generic"):
        alert = normalize_alert(source, sample_payload(source, "firing_error_rate"))
        assert (alert.occurrences, alert.starts_at, alert.ends_at) == ((), "", ""), source


def test_as_dict_is_json_safe_and_a_base_fields_only_alert_reads():
    stored = normalize_alert("alertmanager", ALERTMANAGER_V034).as_dict()

    assert json.loads(json.dumps(stored)) == stored
    assert stored["occurrences"] == [["a1b2c3d4e5f60718", "2026-10-15T10:00:00Z"],
                                     ["b2c3d4e5f6a70819", "2026-10-15T10:01:30.512345Z"]]
    base_fields_only = {"title": "HighErrorRate · sample-api", "status": "firing", "severity": "critical", "fingerprint": "f",
              "source_type": "alertmanager", "reference": "", "summary": "s", "labels": {"service": "sample-api"}}
    old = NormalizedAlert(**base_fields_only)
    assert (old.starts_at, old.occurrences, old.common_labels, old.annotations) == ("", (), {}, {})
    assert old.as_dict()["occurrences"] == []


def test_instants_parse_to_utc_and_zero_or_bad_values_are_none():
    assert parse_instant("2026-10-15T10:00:00.123456789Z").isoformat() == "2026-10-15T10:00:00.123456+00:00"
    assert parse_instant("2026-10-15T12:00:00+02:00").isoformat() == "2026-10-15T10:00:00+00:00"
    for value in ("", None, "0001-01-01T00:00:00Z", "yesterday", 17):
        assert parse_instant(value) is None
