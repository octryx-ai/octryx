"""Which service an alert is about: the Workspace's alert targets."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ...models import Project
from ..workflow_checks.evidence_families import FAMILIES as EVIDENCE_FAMILIES
from .normalize import SOURCE_TYPES, NormalizedAlert

CONFIG_KEY = "alert_targets"

REASON_UNMAPPED = "alert_target_unmapped"
REASON_AMBIGUOUS = "alert_target_ambiguous"
REASON_INVALID = "alert_targets_invalid"


MAX_TARGETS = 200
MAX_MATCH_LABELS = 20
MAX_LABEL_VALUE = 120
MAX_SELECTOR = 500
MAX_JENKINS_JOBS = 20
MAX_LOOKBACK_MINUTES = 24 * 60
MAX_REOPEN_WINDOW_MINUTES = 7 * 24 * 60
DEFAULT_LOOKBACK_MINUTES = 30
DEFAULT_REOPEN_WINDOW_MINUTES = 60

_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,79}$")
_LABEL_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,99}$")
_KEYS = frozenset({"id", "service", "match", "kubernetes", "logs", "metrics", "ci", "servicenow",
                   "required_families", "lookback_minutes", "reopen_window_minutes"})


@dataclass(frozen=True)
class AlertTarget:
    id: str
    service: str
    match: dict[str, Any]
    kubernetes: dict | None = None
    logs: dict | None = None
    metrics: dict | None = None
    ci: dict | None = None
    servicenow: dict | None = None
    required_families: tuple[str, ...] = ()
    lookback_minutes: int = DEFAULT_LOOKBACK_MINUTES
    reopen_window_minutes: int = DEFAULT_REOPEN_WINDOW_MINUTES

    def as_context(self) -> dict:
        return {
            "id": self.id,
            "service": self.service,
            "match": {key: dict(value) if isinstance(value, dict) else value for key, value in self.match.items()},
            "kubernetes": dict(self.kubernetes) if self.kubernetes else None,
            "logs": dict(self.logs) if self.logs else None,
            "metrics": dict(self.metrics) if self.metrics else None,
            "ci": {"jenkins_jobs": list(self.ci.get("jenkins_jobs") or [])} if self.ci else None,
            "servicenow": dict(self.servicenow) if self.servicenow else None,
            "required_families": list(self.required_families),
            "lookback_minutes": self.lookback_minutes,
            "reopen_window_minutes": self.reopen_window_minutes,
        }

    def matches(self, alert: NormalizedAlert) -> bool:
        source = self.match.get("source_type")
        if source and source != alert.source_type:
            return False
        labels = alert_match_labels(alert)
        wanted = self.match.get("labels") or {}
        return bool(wanted) and all(labels.get(name) == value for name, value in wanted.items())


@dataclass(frozen=True)
class TargetMatch:
    target: AlertTarget | None
    reason: str | None  # alert_target_unmapped | alert_target_ambiguous | alert_targets_invalid


def alert_match_labels(alert: NormalizedAlert) -> dict[str, str]:
    labels = alert.common_labels or alert.labels
    return {str(key): str(value) for key, value in (labels or {}).items() if isinstance(value, str)}


def _text(value: Any, *, limit: int) -> str | None:
    return value if isinstance(value, str) and value.strip() and len(value) <= limit else None


def _minutes(entry: dict, name: str, default: int, maximum: int, errors: list[str], where: str) -> int:
    value = entry.get(name, default)
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= maximum:
        errors.append(f"{where}: {name} must be a whole number of minutes between 0 and {maximum}")
        return default
    return value


def _match(raw: Any, errors: list[str], where: str) -> dict[str, Any]:
    if not isinstance(raw, dict) or set(raw) - {"source_type", "labels"}:
        errors.append(f"{where}: match takes only source_type and labels")
        return {}
    match: dict[str, Any] = {}
    source = raw.get("source_type")
    if source is not None:
        if source not in SOURCE_TYPES:
            errors.append(f"{where}: match.source_type is not a known source")
        else:
            match["source_type"] = source
    labels = raw.get("labels")
    if not isinstance(labels, dict) or not labels or len(labels) > MAX_MATCH_LABELS:
        errors.append(f"{where}: match.labels needs 1 to {MAX_MATCH_LABELS} labels")
        return match
    exact: dict[str, str] = {}
    for name, value in labels.items():
        if not isinstance(name, str) or not _LABEL_NAME.match(name):
            errors.append(f"{where}: match label names are Prometheus label names")
        elif _text(value, limit=MAX_LABEL_VALUE) is None or value != value.strip():
            errors.append(f"{where}: match label '{name}' needs an exact, non-empty value")
        else:
            exact[name] = value
    match["labels"] = exact
    return match


def _selector(raw: Any, errors: list[str], where: str, name: str) -> dict | None:
    if raw is None:
        return None
    if not isinstance(raw, dict) or set(raw) != {"selector"} or _text(raw.get("selector"), limit=MAX_SELECTOR) is None:
        errors.append(f"{where}: {name} takes a non-empty selector")
        return None
    return {"selector": raw["selector"]}


def _kubernetes(raw: Any, errors: list[str], where: str) -> dict | None:
    if raw is None:
        return None
    if not isinstance(raw, dict) or set(raw) - {"namespace", "connection_id"}:
        errors.append(f"{where}: kubernetes takes namespace and connection_id")
        return None
    namespace = raw.get("namespace")
    if not isinstance(namespace, str) or not re.match(r"^[a-z0-9]([-a-z0-9]{0,61}[a-z0-9])?$", namespace):
        errors.append(f"{where}: kubernetes.namespace must be one Kubernetes namespace name")
        return None
    connection = raw.get("connection_id")
    if connection is not None and _text(connection, limit=64) is None:
        errors.append(f"{where}: kubernetes.connection_id must be an id or null")
        return None
    return {"namespace": namespace, "connection_id": connection}


def _ci(raw: Any, errors: list[str], where: str) -> dict | None:
    if raw is None:
        return None
    jobs = raw.get("jenkins_jobs") if isinstance(raw, dict) and set(raw) == {"jenkins_jobs"} else None
    if not isinstance(jobs, list) or len(jobs) > MAX_JENKINS_JOBS or any(
            _text(job, limit=200) is None for job in jobs):
        errors.append(f"{where}: ci takes jenkins_jobs, a list of up to {MAX_JENKINS_JOBS} job names")
        return None
    return {"jenkins_jobs": list(jobs)}


def _servicenow(raw: Any, errors: list[str], where: str) -> dict | None:
    if raw is None:
        return None
    if not isinstance(raw, dict) or set(raw) - {"cmdb_ci"}:
        errors.append(f"{where}: servicenow takes cmdb_ci")
        return None
    item = raw.get("cmdb_ci")
    if item is not None and _text(item, limit=200) is None:
        errors.append(f"{where}: servicenow.cmdb_ci must be a name or null")
        return None
    return {"cmdb_ci": item}


def _families(raw: Any, errors: list[str], where: str) -> tuple[str, ...]:
    if raw is None:
        return ()
    if not isinstance(raw, list) or any(family not in EVIDENCE_FAMILIES for family in raw):
        errors.append(f"{where}: required_families must name evidence families ({', '.join(EVIDENCE_FAMILIES)})")
        return ()
    return tuple(dict.fromkeys(raw))


def _target(entry: Any, index: int, errors: list[str]) -> AlertTarget | None:
    where = f"alert_targets[{index}]"
    if not isinstance(entry, dict):
        errors.append(f"{where}: must be an object")
        return None
    unknown = sorted(str(key) for key in set(entry) - _KEYS)
    if unknown:
        errors.append(f"{where}: unknown keys {', '.join(unknown)}")
    target_id = entry.get("id")
    if not isinstance(target_id, str) or not _ID.match(target_id):
        errors.append(f"{where}: id must be 1-80 letters, digits, '.', '_', ':' or '-'")
        return None
    where = f"alert_targets[{target_id}]"
    service = entry.get("service", target_id)
    if _text(service, limit=MAX_LABEL_VALUE) is None:
        errors.append(f"{where}: service must be a non-empty name")
        service = target_id
    seen = len(errors)
    target = AlertTarget(
        id=target_id,
        service=service,
        match=_match(entry.get("match"), errors, where),
        kubernetes=_kubernetes(entry.get("kubernetes"), errors, where),
        logs=_selector(entry.get("logs"), errors, where, "logs"),
        metrics=_selector(entry.get("metrics"), errors, where, "metrics"),
        ci=_ci(entry.get("ci"), errors, where),
        servicenow=_servicenow(entry.get("servicenow"), errors, where),
        required_families=_families(entry.get("required_families"), errors, where),
        lookback_minutes=_minutes(entry, "lookback_minutes", DEFAULT_LOOKBACK_MINUTES, MAX_LOOKBACK_MINUTES,
                                  errors, where),
        reopen_window_minutes=_minutes(entry, "reopen_window_minutes", DEFAULT_REOPEN_WINDOW_MINUTES,
                                       MAX_REOPEN_WINDOW_MINUTES, errors, where),
    )
    return target if len(errors) == seen and not unknown else None


def parse_alert_targets(raw: Any) -> tuple[list[AlertTarget], list[str]]:
    if raw is None:
        return [], []
    if not isinstance(raw, list):
        return [], ["alert_targets must be a list"]
    if len(raw) > MAX_TARGETS:
        return [], [f"alert_targets holds at most {MAX_TARGETS} targets"]
    errors: list[str] = []
    targets: list[AlertTarget] = []
    for index, entry in enumerate(raw):
        target = _target(entry, index, errors)
        if target is None:
            continue
        if any(existing.id == target.id for existing in targets):
            errors.append(f"alert_targets[{target.id}]: the id is used twice")
            continue
        targets.append(target)
    return targets, errors


async def workspace_alert_targets(db: AsyncSession, project_id: str) -> tuple[list[AlertTarget], list[str]]:
    project = await db.get(Project, project_id) if project_id else None
    config = project.config if project is not None and isinstance(project.config, dict) else {}
    return parse_alert_targets(config.get(CONFIG_KEY))


def map_alert_target(targets: list[AlertTarget], alert: NormalizedAlert) -> TargetMatch:
    matched = [target for target in targets if target.matches(alert)]
    if len(matched) == 1:
        return TargetMatch(matched[0], None)
    return TargetMatch(None, REASON_AMBIGUOUS if matched else REASON_UNMAPPED)


__all__ = [
    "CONFIG_KEY",
    "REASON_AMBIGUOUS",
    "REASON_INVALID",
    "REASON_UNMAPPED",
    "AlertTarget",
    "TargetMatch",
    "alert_match_labels",
    "map_alert_target",
    "parse_alert_targets",
    "workspace_alert_targets",
]
