"""The evidence family contract: what an alert's evidence must answer."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any

from .library import ToolUse

FAMILIES = ("kubernetes", "logs", "metrics", "ci_deploy", "tickets", "knowledge")
OK, EMPTY, UNAVAILABLE, REFUSED = "ok", "empty", "unavailable", "refused"
STATUSES = (OK, EMPTY, UNAVAILABLE, REFUSED)
# Not a record status: the per-family verdict of a family no record answered (or only out of scope).
MISSING = "missing"
ENVELOPE_VERSION = 1

TOOL_FAMILY: dict[str, str] = {
    "get_pod_logs": "kubernetes",
    "list_failed_pods": "kubernetes",
    "get_k8s_events": "kubernetes",
    "query_loki": "logs",
    "query_prometheus": "metrics",
    "list_jenkins_builds": "ci_deploy",
    "get_pipeline_logs": "ci_deploy",
    "list_pipelines": "ci_deploy",
    "aws_deployment_timeline": "ci_deploy",
    "search_jira_tickets": "tickets",
    "get_jira_ticket": "tickets",
    "list_servicenow_incidents": "tickets",
    "get_servicenow_record": "tickets",
    "list_servicenow_changes": "tickets",
    "knowledge_search": "knowledge",
    "knowledge_read": "knowledge",
}
# The server tools that write their own envelope. Only theirs is trusted: any other tool's result could carry
# an ``evidence`` key from remote content.
ENVELOPE_TOOLS = frozenset({"get_pod_logs", "list_failed_pods", "get_k8s_events", "query_loki", "query_prometheus",
                            "list_jenkins_builds"})
# The families whose sources are scoped to the alert target; their records count only for the matching target.
SCOPED_FAMILIES = frozenset({"kubernetes", "logs", "metrics", "ci_deploy"})
WINDOWED_FAMILIES = frozenset({"logs", "metrics", "ci_deploy"})

_REFUSED_STATUSES = frozenset({"denied", "blocked", "refused"})
_REFUSED_KEYS = ("approval_required", "denied", "blocked")
_COUNT_KEYS = ("failed_count", "total_events", "total_lines", "count", "total", "total_count", "streams_count")
_LIST_KEYS = ("builds", "incidents", "changes", "records", "issues", "tickets", "results", "passages", "items",
              "events", "pipelines", "job_logs", "deployments", "streams", "failed_pods")
_RECORD_KEYS = ("record", "issue", "ticket", "content", "text", "logs")
_META_KEYS = frozenset({"source", "query", "jql", "provider", "namespace", "pod", "container", "tail_lines",
                        "_prompt_result_source", "artifact_id", "evidence"})


def evidence_envelope(family: str, status: str, *, target_id: str | None, namespace: str | None,
                      window: dict | None, count: int, reason: str = "") -> dict:
    window = window if isinstance(window, Mapping) else None
    return {
        "v": ENVELOPE_VERSION,
        "family": family,
        "status": status,
        "target_id": target_id or None,
        "namespace": namespace or None,
        "window": {"start": window.get("start"), "end": window.get("end")} if window else None,
        "count": max(0, int(count or 0)),
        "reason": str(reason or "")[:200],
    }


def with_envelope(result: dict[str, Any], envelope: dict[str, Any]) -> dict[str, Any]:
    return {"evidence": envelope, **{key: value for key, value in result.items() if key != "evidence"}}


@dataclass(frozen=True)
class EvidenceRecord:
    family: str
    status: str
    tool: str
    call_id: str
    target_id: str | None
    namespace: str | None
    window_start: str | None
    window_end: str | None
    count: int
    reason: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _shape_count(result: Mapping[str, Any]) -> int:
    for key in _COUNT_KEYS:
        value = result.get(key)
        if type(value) is int:
            return max(0, value)
    for key in _LIST_KEYS:
        value = result.get(key)
        if isinstance(value, list):
            return len(value)
    for key in _RECORD_KEYS:
        value = result.get(key)
        if isinstance(value, Mapping | list | str) and value:
            return 1
    return 1 if any(value for key, value in result.items() if key not in _META_KEYS) else 0


def _shape_status(use: ToolUse, result: Any) -> tuple[str, int, str]:
    if not isinstance(result, Mapping):
        return UNAVAILABLE, 0, "no result"
    status = str(result.get("status") or "").strip().lower()
    error = result.get("error")
    reason = str(result.get("code") or result.get("error_code") or error or "")[:200]
    if status in _REFUSED_STATUSES or any(result.get(key) for key in _REFUSED_KEYS):
        return REFUSED, 0, reason or status or "refused"
    if error:
        text = str(error).lower()
        if "not allowed" in text or "out_of_scope" in text or "permission" in text:
            return REFUSED, 0, reason
        return UNAVAILABLE, 0, reason
    if not use.succeeded:
        return UNAVAILABLE, 0, reason or "the call did not succeed"
    count = _shape_count(result)
    return (OK if count > 0 else EMPTY), count, ""


def classify_tool_use(use: ToolUse) -> EvidenceRecord | None:
    family = TOOL_FAMILY.get(str(use.name or ""))
    if family is None or use.result is None:
        return None
    result = use.result
    envelope = result.get("evidence") if isinstance(result, Mapping) and use.name in ENVELOPE_TOOLS else None
    if (isinstance(envelope, Mapping) and envelope.get("v") == ENVELOPE_VERSION
            and envelope.get("family") == family and envelope.get("status") in STATUSES):
        window = envelope.get("window") if isinstance(envelope.get("window"), Mapping) else {}
        status = str(envelope["status"])
        if status in (OK, EMPTY) and not use.succeeded:
            # The envelope said data; the call itself failed (e.g. a later error): never more than unavailable.
            status = UNAVAILABLE
        count = envelope.get("count")
        return EvidenceRecord(family, status, use.name, use.call_id, _str(envelope.get("target_id")),
                              _str(envelope.get("namespace")), _str(window.get("start")), _str(window.get("end")),
                              count if type(count) is int and count >= 0 else 0, str(envelope.get("reason") or ""))
    status, count, reason = _shape_status(use, result)
    return EvidenceRecord(family, status, use.name, use.call_id, None, None, None, None, count, reason)


def records_of(uses: Sequence[ToolUse]) -> list[dict[str, Any]]:
    return [record.as_dict() for record in map(classify_tool_use, uses) if record is not None]


def _str(value: Any) -> str | None:
    text = str(value).strip() if value is not None else ""
    return text or None


def _parse_time(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        moment = value
    elif isinstance(value, str) and value.strip():
        try:
            moment = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    return moment.replace(tzinfo=UTC) if moment.tzinfo is None else moment.astimezone(UTC)


def is_agent_refusal(reason: str) -> bool:
    text = str(reason or "")
    return text.endswith("_out_of_scope") or text.startswith("invalid_")


@dataclass(frozen=True)
class _Scope:
    target_id: str | None
    namespace: str | None
    window_start: datetime | None
    window_end: datetime | None


def _scope(scope: Mapping[str, Any] | None) -> _Scope | None:
    if not isinstance(scope, Mapping):
        return None
    kubernetes = scope.get("kubernetes") if isinstance(scope.get("kubernetes"), Mapping) else {}
    window = scope.get("window") if isinstance(scope.get("window"), Mapping) else {}
    return _Scope(_str(scope.get("target_id") or scope.get("id")), _str(scope.get("namespace") or
                                                                       kubernetes.get("namespace")),
                  _parse_time(window.get("start")), _parse_time(window.get("end")))


def required_families_of(scope: Mapping[str, Any] | None) -> list[str]:
    raw = scope.get("required_families") if isinstance(scope, Mapping) else None
    return [str(item) for item in raw if str(item) in FAMILIES] if isinstance(raw, list | tuple) else []


def _in_window(record: Mapping[str, Any], scope: _Scope) -> bool:
    if scope.window_start is None or str(record.get("family") or "") not in WINDOWED_FAMILIES:
        return True
    start, end = _parse_time(record.get("window_start")), _parse_time(record.get("window_end"))
    if start is None or end is None:
        return False
    return start < (scope.window_end or datetime.max.replace(tzinfo=UTC)) and end > scope.window_start


def _matches(record: Mapping[str, Any], scope: _Scope | None) -> bool:
    family = str(record.get("family") or "")
    target = _str(record.get("target_id"))
    if family in SCOPED_FAMILIES and scope is not None and scope.target_id and target != scope.target_id:
        return False
    if (family == "kubernetes" and scope is not None and scope.namespace
            and _str(record.get("namespace")) not in (None, scope.namespace)):
        return False
    if str(record.get("status")) == EMPTY and (target is None or family not in SCOPED_FAMILIES):
        return False  # an empty answer without a target is no negative for the target
    return scope is None or _in_window(record, scope)


def evaluate_families(records: Sequence[dict], *, required: Sequence[str], scope: dict | None
                      ) -> tuple[str, str, bool, dict[str, str]]:
    from .library import FAILED, PASSED

    wanted = [family for family in dict.fromkeys(str(item) for item in required) if family in FAMILIES]
    if not wanted:
        return FAILED, "needs_configuration: no required evidence family", False, {}
    resolved = _scope(scope)
    statuses: dict[str, str] = {}
    reasons: dict[str, str] = {}
    unresolved = True
    for family in wanted:
        mine = [record for record in records if isinstance(record, Mapping) and record.get("family") == family]
        passing = [record for record in mine if record.get("status") in (OK, EMPTY) and _matches(record, resolved)]
        if passing:
            statuses[family] = OK if any(record.get("status") == OK for record in passing) else EMPTY
            continue
        platform = [record for record in mine if record.get("status") == UNAVAILABLE or (
            record.get("status") == REFUSED and not is_agent_refusal(str(record.get("reason") or "")))]
        if platform:
            last = platform[-1]
            statuses[family] = str(last.get("status"))
            reasons[family] = str(last.get("reason") or "")[:120]
            continue
        refused = [record for record in mine if record.get("status") == REFUSED]
        statuses[family] = REFUSED if refused else MISSING
        reasons[family] = (str(refused[-1].get("reason") or "")[:120] if refused else
                           "out of the alert target or window" if mine else "no call")
        unresolved = False
    detail = "; ".join(f"{family}: {statuses[family]}" + (f" ({reasons[family]})" if reasons.get(family) else "")
                       for family in wanted)
    if all(statuses[family] in (OK, EMPTY) for family in wanted):
        return PASSED, detail, False, statuses
    return FAILED, detail, unresolved, statuses


def _alert_readers() -> tuple[Any, Any]:
    from ..workflow_runs.alert_context import alert_target_of, alert_window_of

    return alert_target_of, alert_window_of


def alert_gate_scope(run: Any) -> dict[str, Any] | None:
    target_of, window_of = _alert_readers()
    target = target_of(run)
    if not isinstance(target, Mapping):
        return None
    kubernetes = target.get("kubernetes") if isinstance(target.get("kubernetes"), Mapping) else {}
    window = window_of(run)
    return {
        "target_id": _str(target.get("id") or target.get("target_id")),
        "namespace": _str(kubernetes.get("namespace")),
        "required_families": required_families_of(target),
        "window": ({"start": _iso(window[0]), "end": _iso(window[1]) if window[1] else None} if window else None),
    }


async def session_gate_scope(db: Any, session_id: str | None) -> dict[str, Any] | None:
    from ..workflow_runs.records import active_run_for_session

    run = await active_run_for_session(db, session_id) if db is not None else None
    return alert_gate_scope(run) if run is not None else None


def _iso(value: datetime) -> str:
    moment = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
    return moment.isoformat().replace("+00:00", "Z")


__all__ = [
    "EMPTY",
    "ENVELOPE_TOOLS",
    "FAMILIES",
    "MISSING",
    "OK",
    "REFUSED",
    "TOOL_FAMILY",
    "UNAVAILABLE",
    "EvidenceRecord",
    "alert_gate_scope",
    "classify_tool_use",
    "evaluate_families",
    "evidence_envelope",
    "is_agent_refusal",
    "records_of",
    "required_families_of",
    "session_gate_scope",
    "with_envelope",
]
