"""Is this alert one the platform already analyses?"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import TaskRun, WorkflowRun
from ...models.integration.webhook import Webhook, WebhookEvent
from ...models.runtime.workflow_run import WorkflowRunSession
from ...time_utils import ensure_utc
from . import normalize as _normalize
from .normalize import NormalizedAlert
from .targets import DEFAULT_REOPEN_WINDOW_MINUTES, AlertTarget, alert_match_labels

KIND_NEW = "new"
KIND_SAME_OCCURRENCE = "same_occurrence"
KIND_RECURRENCE = "recurrence"
KIND_REOPEN = "reopen"
DEDUP_KINDS = (KIND_NEW, KIND_SAME_OCCURRENCE, KIND_RECURRENCE, KIND_REOPEN)

OCCURRENCE_SOURCE_TYPES = frozenset({"alertmanager", "grafana"})
CANDIDATE_LIMIT = 50
MAX_OCCURRENCES = 50

# Outcomes whose event is tied to a run (``grouped`` points at the run it joined).
_LINKED_OUTCOMES = ("started", "completed", "failed", "grouped")
_OPEN_TASK_RUN_STATUSES = frozenset({"pending", "queued", "running"})
_OPEN_WORKFLOW_STATUSES = frozenset({"running", "waiting", "paused"})
_RANK = {"critical": 3, "warning": 2, "unknown": 1, "info": 0}

Pair = tuple[str, str]


def dedup_key(service: str, fingerprint: str) -> str:
    return hashlib.sha256(json.dumps([str(service or ""), str(fingerprint or "")]).encode()).hexdigest()


@dataclass(frozen=True)
class DedupDecision:
    kind: str  # new | same_occurrence | recurrence | reopen
    key: str
    occurrences: tuple[tuple[str, str], ...]
    linked_task_run_id: str | None = None
    linked_workflow_run_id: str | None = None
    escalated: bool = False  # new severity rank > linked run's
    new_occurrences: tuple[tuple[str, str], ...] = field(default=(), compare=False)

    @property
    def groups(self) -> bool:
        return self.kind in (KIND_SAME_OCCURRENCE, KIND_RECURRENCE)

    def as_dict(self) -> dict:
        data: dict[str, Any] = {
            "kind": self.kind,
            "key": self.key,
            "occurrences": [list(pair) for pair in self.occurrences],
            "linked_task_run_id": self.linked_task_run_id,
            "linked_workflow_run_id": self.linked_workflow_run_id,
            "escalated": self.escalated,
        }
        if self.kind == KIND_REOPEN:
            data["reopens"] = {"task_run_id": self.linked_task_run_id,
                               "workflow_run_id": self.linked_workflow_run_id}
        return data


def occurrences_of(alert: NormalizedAlert) -> tuple[Pair, ...]:
    if alert.source_type not in OCCURRENCE_SOURCE_TYPES:
        return ()
    pairs: list[Pair] = []
    for item in alert.occurrences or ():
        if isinstance(item, (list, tuple)) and len(item) == 2 and all(isinstance(part, str) for part in item):
            if item[0] and item[1]:
                pairs.append((item[0], item[1]))
    return tuple(dict.fromkeys(pairs))[:MAX_OCCURRENCES]


def service_of(alert: NormalizedAlert, target: AlertTarget | None) -> str:
    if target is not None:
        return target.service
    labels = alert_match_labels(alert)
    return labels.get("service") or labels.get("job") or ""


def rank(severity: str | None) -> int:
    return _RANK.get(str(severity or "unknown"), 1)


@dataclass
class _Thread:
    task_run_id: str | None
    newest: datetime
    pairs: set[Pair] = field(default_factory=set)
    keys: set[str] = field(default_factory=set)
    severity: int = -1
    workflow_run_id: str | None = None
    open: bool = False
    ended_at: datetime | None = None

    @property
    def fingerprints(self) -> set[str]:
        return {fingerprint for fingerprint, _ in self.pairs}


def _stored_alert(source_type: str, payload: Any) -> NormalizedAlert | None:
    if not isinstance(payload, dict) or payload.get("truncated") or payload.get("unreadable"):
        return None
    try:
        return _normalize.normalize_alert(source_type, payload)
    except Exception:  # a stored payload is data; one that no longer reads is skipped, never a failed alert
        return None


def _run_dedup(run: TaskRun | None) -> dict:
    payload = run.input_ if run is not None and isinstance(run.input_, dict) else {}
    alert = payload.get("inbound_alert") if isinstance(payload.get("inbound_alert"), dict) else {}
    dedup = alert.get("dedup") if isinstance(alert.get("dedup"), dict) else {}
    return {"dedup": dedup, "severity": (alert.get("alert") or {}).get("severity")}


async def _candidates(db: AsyncSession, webhook: Webhook, fingerprint: str, key: str
                      ) -> list[tuple[WebhookEvent, TaskRun | None]]:
    base = (
        select(WebhookEvent, TaskRun)
        .outerjoin(TaskRun, TaskRun.id == WebhookEvent.task_run_id)
        .where(WebhookEvent.webhook_id == webhook.id, WebhookEvent.is_test.is_(False),
               WebhookEvent.outcome.in_(_LINKED_OUTCOMES))
        .order_by(WebhookEvent.received_at.desc(), WebhookEvent.id.desc())
        .limit(CANDIDATE_LIMIT)
    )
    same = or_(WebhookEvent.fingerprint == fingerprint,
               TaskRun.input_[("inbound_alert", "dedup", "key")].as_string() == key)
    rows: dict[str, tuple[WebhookEvent, TaskRun | None]] = {}
    # The recency scan finds a group whose fingerprint changed because it gained or lost an alert.
    for query in (base.where(same), base):
        for event, run in (await db.execute(query)).all():
            rows.setdefault(event.id, (event, run))
    return list(rows.values())


async def _workflow_run(db: AsyncSession, run: TaskRun | None, event: WebhookEvent) -> WorkflowRun | None:
    session_id = (run.session_id if run is not None else None) or event.session_id
    if not session_id:
        return None
    return (await db.execute(
        select(WorkflowRun)
        .join(WorkflowRunSession, WorkflowRunSession.run_id == WorkflowRun.id)
        .where(WorkflowRunSession.session_id == session_id, WorkflowRun.parent_run_id.is_(None))
        .order_by(WorkflowRunSession.linked_at.asc())
        .limit(1)
    )).scalar_one_or_none()


async def _threads(db: AsyncSession, webhook: Webhook, rows: list[tuple[WebhookEvent, TaskRun | None]]
                   ) -> list[_Thread]:
    threads: dict[str, _Thread] = {}
    runs: dict[str, TaskRun | None] = {}
    first_event: dict[str, WebhookEvent] = {}
    source_type = webhook.source_type or "generic"
    for event, run in rows:
        if event.outcome == "grouped" and not event.task_run_id:
            continue  # grouped while its run was still being queued: it names no run of its own
        thread_id = event.task_run_id or f"event:{event.id}"
        received = ensure_utc(event.received_at)
        thread = threads.get(thread_id)
        if thread is None:
            thread = threads[thread_id] = _Thread(task_run_id=event.task_run_id, newest=received)
            runs[thread_id] = run
            first_event[thread_id] = event
        thread.newest = max(thread.newest, received)
        stored = _stored_alert(source_type, event.raw_payload)
        if stored is not None:
            thread.pairs.update(occurrences_of(stored))
            thread.severity = max(thread.severity, rank(stored.severity))
        if event.fingerprint:
            thread.keys.add(f"fingerprint:{event.fingerprint}")
    for thread_id, thread in threads.items():
        run, event = runs[thread_id], first_event[thread_id]
        recorded = _run_dedup(run)
        thread.pairs.update(tuple(pair) for pair in recorded["dedup"].get("occurrences") or []
                            if isinstance(pair, (list, tuple)) and len(pair) == 2)
        if recorded["dedup"].get("key"):
            thread.keys.add(str(recorded["dedup"]["key"]))
        if recorded["severity"]:
            thread.severity = max(thread.severity, rank(recorded["severity"]))
        workflow = await _workflow_run(db, run, event)
        if workflow is not None:
            thread.workflow_run_id = workflow.id
            thread.open = workflow.status in _OPEN_WORKFLOW_STATUSES
            thread.ended_at = None if thread.open else ensure_utc(workflow.completed_at or workflow.updated_at)
        elif run is not None:
            thread.open = (run.status or "") in _OPEN_TASK_RUN_STATUSES
            ended = run.completed_at or event.processed_at
            thread.ended_at = None if thread.open else ensure_utc(ended) if ended else thread.newest
        else:
            # A started event whose run is not queued yet (the trigger commits the event first) is open; one that
            # failed to queue is over.
            thread.open = event.outcome == "started"
            thread.ended_at = None if thread.open else ensure_utc(event.processed_at or event.received_at)
    return sorted(threads.values(), key=lambda item: item.newest, reverse=True)


def _decision(kind: str, key: str, pairs: tuple[Pair, ...], thread: _Thread | None, *, severity: int,
              new_pairs: tuple[Pair, ...] = ()) -> DedupDecision:
    if thread is None:
        return DedupDecision(kind, key, pairs, new_occurrences=pairs)
    return DedupDecision(kind, key, pairs, linked_task_run_id=thread.task_run_id,
                         linked_workflow_run_id=thread.workflow_run_id, escalated=severity > thread.severity >= 0,
                         new_occurrences=new_pairs)


async def find_dedup(db: AsyncSession, webhook: Webhook, alert: NormalizedAlert, target: AlertTarget | None, *,
                     now: datetime) -> DedupDecision:
    pairs = occurrences_of(alert)
    key = dedup_key(service_of(alert, target), alert.fingerprint)
    if not pairs:
        return DedupDecision(KIND_NEW, key, ())
    threads = await _threads(db, webhook, await _candidates(db, webhook, alert.fingerprint, key))
    severity = rank(alert.severity)
    reopen_window = timedelta(minutes=target.reopen_window_minutes if target is not None
                              else DEFAULT_REOPEN_WINDOW_MINUTES)
    wanted, fingerprints = set(pairs), {fingerprint for fingerprint, _ in pairs}
    current = ensure_utc(now)

    def within_reopen(thread: _Thread) -> bool:
        return thread.ended_at is not None and current - thread.ended_at <= reopen_window

    seen_anywhere = set().union(*(thread.pairs for thread in threads)) if threads else set()
    new_pairs = tuple(pair for pair in pairs if pair not in seen_anywhere)
    overlapping = next((thread for thread in threads if thread.pairs & wanted), None)
    if overlapping is not None:
        if overlapping.open:
            return _decision(KIND_SAME_OCCURRENCE, key, pairs, overlapping, severity=severity, new_pairs=new_pairs)
        decision = _decision(KIND_SAME_OCCURRENCE, key, pairs, overlapping, severity=severity, new_pairs=new_pairs)
        if decision.escalated:
            return _decision(KIND_REOPEN, key, pairs, overlapping, severity=severity, new_pairs=new_pairs)
        if not new_pairs:
            return decision  # the same occurrence after the run ended is grouped, never re-analysed
        return (_decision(KIND_REOPEN, key, pairs, overlapping, severity=severity, new_pairs=new_pairs)
                if within_reopen(overlapping) else _decision(KIND_NEW, key, pairs, None, severity=severity))
    same_group = f"fingerprint:{alert.fingerprint}"
    series = next((thread for thread in threads
                   if key in thread.keys or same_group in thread.keys or thread.fingerprints & fingerprints), None)
    if series is None:
        return _decision(KIND_NEW, key, pairs, None, severity=severity)
    if series.open:
        return _decision(KIND_RECURRENCE, key, pairs, series, severity=severity, new_pairs=new_pairs)
    if within_reopen(series):
        return _decision(KIND_REOPEN, key, pairs, series, severity=severity, new_pairs=new_pairs)
    return _decision(KIND_NEW, key, pairs, None, severity=severity)


__all__ = [
    "DEDUP_KINDS",
    "KIND_NEW",
    "KIND_RECURRENCE",
    "KIND_REOPEN",
    "KIND_SAME_OCCURRENCE",
    "OCCURRENCE_SOURCE_TYPES",
    "DedupDecision",
    "dedup_key",
    "find_dedup",
    "occurrences_of",
    "service_of",
]
