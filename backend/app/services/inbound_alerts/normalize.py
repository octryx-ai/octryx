"""One shape for an incoming alert, whatever sent it."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

SOURCE_TYPES = (
    "alertmanager",
    "grafana",
    "datadog",
    "pagerduty",
    "sentry",
    "generic",
    "jira_change",
    "servicenow_change",
    "scm_pull_request",
    "ci_build",
)
SOURCE_LABELS = {
    "alertmanager": "Alertmanager",
    "grafana": "Grafana",
    "datadog": "Datadog",
    "pagerduty": "PagerDuty",
    "sentry": "Sentry",
    "generic": "Any JSON",
    "jira_change": "Jira change",
    "servicenow_change": "ServiceNow change",
    "scm_pull_request": "Pull request (GitHub, GitLab, Bitbucket)",
    "ci_build": "CI build (GitHub Actions, GitLab, Jenkins)",
}
# Sources that move waiting workflow runs instead of starting an Action.
RUN_EVENT_SOURCE_TYPES = frozenset({"scm_pull_request", "ci_build"})
# Sources that arrive through a connector poll instead of a URL.
POLLED_SOURCE_TYPES = frozenset({"jira_change", "servicenow_change"})

_SEVERITY = {
    "critical": "critical", "crit": "critical", "high": "critical", "p1": "critical", "error": "critical",
    "fatal": "critical", "page": "critical", "sev1": "critical", "emergency": "critical",
    "warning": "warning", "warn": "warning", "medium": "warning", "p2": "warning", "p3": "warning",
    "major": "warning", "minor": "warning", "sev2": "warning", "sev3": "warning", "normal": "warning",
    "info": "info", "informational": "info", "low": "info", "p4": "info", "p5": "info", "debug": "info",
    "none": "info",
}
_RESOLVED = frozenset({"resolved", "recovered", "ok", "closed", "inactive", "normal_recovery"})
_RANK = {"critical": 3, "warning": 2, "unknown": 1, "info": 0}
MAX_OCCURRENCES = 50
MAX_LABELS = 40
MAX_LABEL_VALUE = 120
MAX_ANNOTATIONS = 20
MAX_ANNOTATION_VALUE = 500


@dataclass(frozen=True)
class NormalizedAlert:
    title: str
    status: str  # firing | resolved
    severity: str  # critical | warning | info | unknown
    fingerprint: str
    source_type: str
    reference: str = ""
    summary: str = ""
    labels: dict[str, str] = field(default_factory=dict)
    # Keyword fields with defaults, so a stored alert dict without them still reads.
    starts_at: str = ""
    ends_at: str = ""
    occurrences: tuple[tuple[str, str], ...] = ()
    common_labels: dict[str, str] = field(default_factory=dict)
    annotations: dict[str, str] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "title": self.title, "status": self.status, "severity": self.severity, "fingerprint": self.fingerprint,
            "source_type": self.source_type, "reference": self.reference, "summary": self.summary,
            "labels": dict(self.labels), "starts_at": self.starts_at, "ends_at": self.ends_at,
            "occurrences": [[fingerprint, started] for fingerprint, started in self.occurrences],
            "common_labels": dict(self.common_labels), "annotations": dict(self.annotations),
        }


def severity_of(value: Any) -> str:
    return _SEVERITY.get(str(value or "").strip().lower(), "unknown")


def _text(value: Any, limit: int = 300) -> str:
    return str(value or "").strip()[:limit]


def _hash(*parts: Any) -> str:
    return hashlib.sha256(json.dumps(parts, sort_keys=True, default=str).encode()).hexdigest()[:64]


def _status(value: Any) -> str:
    return "resolved" if str(value or "").strip().lower() in _RESOLVED else "firing"


def parse_instant(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    parsed = parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)
    # Alertmanager sends ``0001-01-01T00:00:00Z`` as the end of a firing alert: no instant.
    return parsed if parsed.year > 1970 else None


def iso_instant(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _exact(value: Any, limit: int) -> str:
    # Not stripped and never cut to a shorter equal value: target mapping matches these exactly, so a value over the
    # limit ends in an ellipsis that no configured value of at most ``limit`` characters can equal.
    text = value if isinstance(value, str) else json.dumps(value, default=str) if value is not None else ""
    return text if len(text) <= limit else text[: limit - 1] + "\u2026"


def _bounded_map(raw: Any, *, keys: int, limit: int) -> dict[str, str]:
    if not isinstance(raw, dict):
        return {}
    items = sorted((str(key), value) for key, value in raw.items())[:keys]
    return {_exact(key, MAX_LABEL_VALUE): _exact(value, limit) for key, value in items}


def _prometheus_style(payload: dict, source_type: str) -> NormalizedAlert:
    alerts = [item for item in payload.get("alerts") or [] if isinstance(item, dict)]
    firing = [item for item in alerts if _status(item.get("status") or payload.get("status")) == "firing"]
    shown = firing or alerts
    first = shown[0] if shown else {}
    labels = {str(k): _text(v, 120) for k, v in (first.get("labels") or {}).items()} if first else {}
    name = labels.get("alertname") or _text(payload.get("title")) or "Alert"
    target = labels.get("service") or labels.get("job") or labels.get("instance") or ""
    title = f"{name} · {target}" if target else name
    if len(shown) > 1:
        title = f"{title} (+{len(shown) - 1} more)"
    severity = max((severity_of((item.get("labels") or {}).get("severity")) for item in shown),
                   key=lambda value: _RANK[value], default="unknown")
    fingerprints = sorted(str(item.get("fingerprint") or _hash(item.get("labels") or {})) for item in shown)
    summary = _text(((first.get("annotations") or {}) if first else {}).get("summary"), 500)
    status = "firing" if firing else _status(payload.get("status") or (first.get("status") if first else ""))
    started = [instant for instant in (parse_instant(item.get("startsAt")) for item in shown) if instant]
    ended = [instant for instant in (parse_instant(item.get("endsAt")) for item in shown) if instant]
    occurrences = sorted({
        (str(item.get("fingerprint") or _hash(item.get("labels") or {}))[:64],
         iso_instant(instant) if (instant := parse_instant(item.get("startsAt"))) else "")
        for item in shown
    })[:MAX_OCCURRENCES]
    common = payload.get("commonLabels")
    common_labels = _bounded_map(common if isinstance(common, dict) and common else (first.get("labels") or {})
                                 if first else {}, keys=MAX_LABELS, limit=MAX_LABEL_VALUE)
    shared = payload.get("commonAnnotations")
    annotations = _bounded_map(shared if isinstance(shared, dict) and shared else (first.get("annotations") or {})
                               if first else {}, keys=MAX_ANNOTATIONS, limit=MAX_ANNOTATION_VALUE)
    return NormalizedAlert(title=_text(title), status=status, severity=severity,
                           fingerprint=_hash(source_type, fingerprints), source_type=source_type, summary=summary,
                           labels=labels, starts_at=iso_instant(min(started)) if started else "",
                           ends_at=iso_instant(max(ended)) if status == "resolved" and ended else "",
                           occurrences=tuple(occurrences), common_labels=common_labels, annotations=annotations)


def _datadog(payload: dict) -> NormalizedAlert:
    transition = _text(payload.get("alert_transition") or payload.get("transition")).lower()
    status = "resolved" if transition in {"recovered", "resolved"} else _status(payload.get("status"))
    title = _text(payload.get("title") or payload.get("event_title") or "Datadog alert")
    severity = severity_of(payload.get("priority") or payload.get("alert_priority") or payload.get("alert_type"))
    key = payload.get("alert_id") or payload.get("aggregate") or title
    return NormalizedAlert(title=title, status=status, severity=severity, fingerprint=_hash("datadog", key),
                           source_type="datadog", reference=_text(payload.get("id"), 80),
                           summary=_text(payload.get("body") or payload.get("text"), 500))


def _pagerduty(payload: dict) -> NormalizedAlert:
    event = payload.get("event") if isinstance(payload.get("event"), dict) else payload
    data = event.get("data") if isinstance(event.get("data"), dict) else {}
    event_type = _text(event.get("event_type")).lower()
    status = "resolved" if event_type.endswith(".resolved") else _status(data.get("status"))
    priority = data.get("priority") if isinstance(data.get("priority"), dict) else {}
    severity = severity_of(priority.get("summary") or data.get("urgency"))
    incident = _text(data.get("id"), 80)
    return NormalizedAlert(title=_text(data.get("title") or "PagerDuty incident"), status=status, severity=severity,
                           fingerprint=_hash("pagerduty", incident or data.get("title")), source_type="pagerduty",
                           reference=incident)


def _sentry(payload: dict) -> NormalizedAlert:
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    issue = data.get("issue") if isinstance(data.get("issue"), dict) else {}
    event = data.get("event") if isinstance(data.get("event"), dict) else {}
    source = issue or event
    status = "resolved" if _text(payload.get("action")).lower() == "resolved" else "firing"
    issue_id = _text(issue.get("id") or event.get("issue_id"), 80)
    return NormalizedAlert(title=_text(source.get("title") or "Sentry issue"), status=status,
                           severity=severity_of(source.get("level")),
                           fingerprint=_hash("sentry", issue_id or source.get("title")), source_type="sentry",
                           reference=issue_id)


def _change(payload: dict, source_type: str) -> NormalizedAlert:
    key = _text(payload.get("key") or payload.get("number") or payload.get("id"), 80)
    title = _text(payload.get("summary") or payload.get("short_description") or key or "Change")
    updated = _text(payload.get("updated") or payload.get("sys_updated_on"), 40)
    return NormalizedAlert(title=f"{key} · {title}" if key and key not in title else title,
                           status=_status(payload.get("status") or payload.get("state")),
                           severity=severity_of(payload.get("priority") or payload.get("severity")),
                           fingerprint=_hash(source_type, key, updated), source_type=source_type, reference=key)


def _generic(payload: dict) -> NormalizedAlert:
    title = _text(payload.get("title") or payload.get("name") or payload.get("summary") or payload.get("message")
                  or "Incoming event")
    key = payload.get("fingerprint") or payload.get("id") or payload.get("alert_id") or title
    return NormalizedAlert(title=title, status=_status(payload.get("status") or payload.get("state")),
                           severity=severity_of(payload.get("severity") or payload.get("priority")),
                           fingerprint=_hash("generic", key), source_type="generic",
                           summary=_text(payload.get("description") or payload.get("details"), 500))


def normalize_alert(source_type: str, payload: Any) -> NormalizedAlert:
    body = payload if isinstance(payload, dict) else {"message": _text(payload, 500)}
    if source_type in {"alertmanager", "grafana"}:
        return _prometheus_style(body, source_type)
    if source_type == "datadog":
        return _datadog(body)
    if source_type == "pagerduty":
        return _pagerduty(body)
    if source_type == "sentry":
        return _sentry(body)
    if source_type in POLLED_SOURCE_TYPES:
        return _change(body, source_type)
    return _generic(body)


__all__ = [
    "MAX_OCCURRENCES",
    "POLLED_SOURCE_TYPES",
    "SOURCE_LABELS",
    "SOURCE_TYPES",
    "NormalizedAlert",
    "iso_instant",
    "normalize_alert",
    "parse_instant",
    "severity_of",
]
