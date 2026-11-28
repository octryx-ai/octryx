"""Workflow run and device job counters for Prometheus (``octryx_workflow_*``, ``octryx_review_*``,
``octryx_pipeline_*``, ``octryx_device_*``)."""

from __future__ import annotations

import time
from collections import OrderedDict
from collections.abc import Callable
from typing import Any

from sqlalchemy import inspect

from .device_report_metrics import DEVICE_CHANGE_RETRIED, DEVICE_CHANGE_UNAVAILABLE, DEVICE_MCP_AUTH_CLEARED
from .metric_types import Counter, Histogram, _Metric

PHASE_SECONDS = (5, 15, 30, 60, 120, 300, 600, 1200, 1800, 3600, 7200, 14400)
DEVICE_TURN_SECONDS = (5, 15, 30, 60, 120, 300, 600, 1200, 1800, 3600, 7200)
_REMEMBERED = 4000

TURN_RUNNING = "accepted"
TURN_ENDS = frozenset({"done", "cancelled", "rejected"})
JOB_ENDS = frozenset({"failed", "device_lost", "closed", "rejected"})

RUN_EVENTS = Counter("octryx_workflow_run_events_total", "Workflow run events by workflow, phase and event kind",
                     ("workflow", "phase", "event"))
PHASE_DURATION = Histogram("octryx_workflow_phase_duration_seconds", "Time a workflow run spent in a phase, by"
                           " workflow, phase and how it left (next, or the run's final status)",
                           ("workflow", "phase", "outcome"), PHASE_SECONDS)
PHASE_TURNS = Counter("octryx_workflow_phase_turns_total", "Phase turns by workflow, phase and state (passed,"
                      " failed)", ("workflow", "phase", "state"))
RUN_PAUSES = Counter("octryx_workflow_run_pauses_total", "Workflow run pauses by workflow, phase and reason",
                     ("workflow", "phase", "reason"))
# Controls audit: who caused each pause, so platform-caused pauses can be seen going down.
PAUSES_BY_CAUSE = Counter("octryx_run_pauses_total", "Workflow run pauses by cause (platform, agent, environment,"
                          " person) and reason (runtime_failed:<code> for a runtime failure)", ("cause", "reason"))
# Run memory: what runs learned per kind, and what a phase was given of it.
RUN_MEMORY_LEARNED = Counter("octryx_run_memory_learned_total", "Run memory entries learned, by kind (test_command,"
                             " environment_fix, denial_alternative)", ("kind",))
RUN_MEMORY_USED = Counter("octryx_run_memory_used_total", "Run memory entries a phase was given at its entry, by"
                          " kind", ("kind",))
RUN_STOPS = Counter("octryx_workflow_run_stops_total", "Workflow runs stopped by workflow and phase",
                    ("workflow", "phase"))
MODEL_REFUSED = Counter("octryx_run_turn_model_refused_total", "Run turns refused for their model, by model and"
                        " profile", ("model", "profile"))
REVIEW_VERDICTS = Counter("octryx_review_verdicts_total", "Independent review verdicts by workflow, phase,"
                          " reviewer engine, model and route", ("workflow", "phase", "engine", "model", "route",
                                                                "verdict"))
REVIEW_FINDINGS = Counter("octryx_review_findings_total", "Review findings by workflow and severity",
                          ("workflow", "severity"))
PIPELINE_REPORTS = Counter("octryx_pipeline_reports_total", "Pipeline reports by workflow and state (green, red,"
                           " ...)", ("workflow", "state"))
SPEC_STUDIO = Counter("octryx_spec_studio_events_total", "Spec Studio events by workflow, event (changed, approved,"
                      " revision_requested) and kind (the change's op, or how it was approved)",
                      ("workflow", "event", "kind"))
WIP_PUSHES = Counter("octryx_wip_push_total", "Work-in-progress pushes by state", ("state",))
WORKSPACE_PREPARATIONS = Counter("octryx_workspace_preparation_total", "Workspace preparations by runtime and"
                                 " state", ("runtime", "state"))
DEVICE_TURNS = Counter("octryx_device_turns_total", "Device turns finished by engine, profile, model, effort (the"
                       " turn's chosen effort, else default) and outcome (done, cancelled, rejected, failed,"
                       " device_lost, closed)",
                       ("engine", "profile", "model", "effort", "outcome"))
DEVICE_TURN_DURATION = Histogram("octryx_device_turn_duration_seconds", "Device turn duration from accepted to"
                                 " its end in seconds", ("engine", "profile"), DEVICE_TURN_SECONDS)
DEVICE_BUSY_WAIT = Histogram("octryx_device_busy_wait_seconds", "Time a turn waited for a full device (device_busy)"
                             " by path (phase, review) and outcome (ran, saturated)", ("path", "outcome"),
                             DEVICE_TURN_SECONDS)
DEVICE_DISCONNECTS = Counter("octryx_device_job_disconnects_total", "Device jobs whose device disconnected, by"
                             " engine", ("engine",))

METRICS: tuple[_Metric, ...] = (RUN_EVENTS, PHASE_DURATION, PHASE_TURNS, RUN_PAUSES, RUN_STOPS, MODEL_REFUSED,
                                REVIEW_VERDICTS, REVIEW_FINDINGS, PIPELINE_REPORTS, SPEC_STUDIO, WIP_PUSHES,
                                WORKSPACE_PREPARATIONS, DEVICE_TURNS, DEVICE_TURN_DURATION, DEVICE_BUSY_WAIT,
                                DEVICE_DISCONNECTS,
                                PAUSES_BY_CAUSE, RUN_MEMORY_LEARNED, RUN_MEMORY_USED,
                                DEVICE_CHANGE_UNAVAILABLE, DEVICE_CHANGE_RETRIED, DEVICE_MCP_AUTH_CLEARED)


class _Remembered(OrderedDict[str, Any]):
    def put(self, key: str, value: Any) -> None:
        self[key] = value
        self.move_to_end(key)
        while len(self) > _REMEMBERED:
            self.popitem(last=False)


_WORKFLOW_OF_RUN = _Remembered()
_PHASE_ENTERED = _Remembered()  # run id -> (phase, monotonic seconds)
_TURN_ACCEPTED = _Remembered()  # job id -> monotonic seconds


def memory_learned(kind: str) -> None:
    RUN_MEMORY_LEARNED.inc(kind=kind)


def reset() -> None:
    for metric in METRICS:
        metric.series.clear()
    for remembered in (_WORKFLOW_OF_RUN, _PHASE_ENTERED, _TURN_ACCEPTED):
        remembered.clear()


def _loaded(row: Any, attribute: str) -> Any:
    return inspect(row).dict.get(attribute)


def _detail(row: Any) -> dict[str, Any]:
    return row.detail if isinstance(row.detail, dict) else {}


def _in_session(session: Any, run_id: str) -> Any:
    from ...models import WorkflowRun

    return session.identity_map.get(session.identity_key(WorkflowRun, run_id)) if session is not None else None


def _workflow(session: Any, run_id: str) -> str:
    from ...models import WorkflowRun

    run = session.identity_map.get(session.identity_key(WorkflowRun, run_id)) if session is not None else None
    if run is not None:
        remember_run(run)
    return str(_WORKFLOW_OF_RUN.get(run_id) or "unknown")


def remember_run(run: Any) -> None:
    run_id, workflow = _loaded(run, "id"), _loaded(run, "workflow_key")
    if run_id and workflow:
        _WORKFLOW_OF_RUN.put(str(run_id), str(workflow))


def _phase_left(run_id: str, workflow: str, outcome: str, now: float) -> Callable[[], None] | None:
    entered = _PHASE_ENTERED.get(run_id)
    if entered is None:
        return None
    phase, started = entered
    return lambda: PHASE_DURATION.observe(max(0.0, now - started), workflow=workflow, phase=phase, outcome=outcome)


def run_event(session: Any, row: Any) -> Callable[[], None]:
    workflow, phase, kind, detail = _workflow(session, row.run_id), row.node_id or "none", row.kind, _detail(row)
    run_id, now = str(row.run_id), time.monotonic()
    counts: list[Callable[[], None]] = [lambda: RUN_EVENTS.inc(workflow=workflow, phase=phase, event=kind)]
    if kind == "node_entered":
        left = _phase_left(run_id, workflow, "next", now)
        if left is not None:
            counts.append(left)
        counts.append(lambda: _PHASE_ENTERED.put(run_id, (phase, now)))
    elif kind == "paused":
        from ..workflow_runs.pause_causes import cause_of, metric_reason

        reason = detail.get("reason")
        cause = str(detail.get("cause") or cause_of(str(reason or ""), detail)[0])
        labelled = metric_reason(str(reason or ""), detail)
        counts.append(lambda: RUN_PAUSES.inc(workflow=workflow, phase=phase, reason=reason))
        counts.append(lambda: PAUSES_BY_CAUSE.inc(cause=cause, reason=labelled))
    elif kind == "stopped":
        counts.append(lambda: RUN_STOPS.inc(workflow=workflow, phase=phase))
    elif kind == "run_memory_used":
        for used, number in dict(detail.get("counts") or {}).items():
            counts.append(lambda used=used, number=number: RUN_MEMORY_USED.inc(int(number), kind=used))
    elif kind == "phase_turn":
        state = detail.get("state")
        counts.append(lambda: PHASE_TURNS.inc(workflow=workflow, phase=phase, state=state))
    elif kind == "run_turn_model_refused":
        model, profile = detail.get("model"), detail.get("profile")
        counts.append(lambda: MODEL_REFUSED.inc(model=model, profile=profile))
    elif kind == "review_verdict":
        counts.append(_review(workflow, phase, detail))
    elif kind == "pipeline_reported":
        from . import run_quality_metrics

        state = detail.get("state")
        counts.append(lambda: PIPELINE_REPORTS.inc(workflow=workflow, state=state))
        counts.append(lambda: run_quality_metrics.pipeline_reported(workflow, detail))
    elif kind.startswith("spec_studio_"):
        event, how = kind.removeprefix("spec_studio_"), detail.get("op") or detail.get("how") or ""
        counts.append(lambda: SPEC_STUDIO.inc(workflow=workflow, event=event, kind=how))
    elif kind in ("wip_pushed", "wip_failed"):
        state = detail.get("state") or kind.removeprefix("wip_")
        counts.append(lambda: WIP_PUSHES.inc(state=state))
    elif kind == "workspace_preparation_reported":
        runtime, state = detail.get("runtime"), detail.get("state")
        counts.append(lambda: WORKSPACE_PREPARATIONS.inc(runtime=runtime, state=state))
    from . import maintenance_metrics

    # Findings per check and what reached main (the run as this session holds it; never a database load).
    maintenance = maintenance_metrics.run_event(workflow, run_id, kind, detail, run=_in_session(session, run_id))
    if maintenance is not None:
        counts.append(maintenance)

    def count() -> None:
        for one in counts:
            one()

    return count


def _review(workflow: str, phase: str, detail: dict[str, Any]) -> Callable[[], None]:
    labels = {"workflow": workflow, "phase": phase, "engine": detail.get("reviewer_engine"),
              "model": detail.get("reviewer_model"),
              "route": detail.get("reviewer_route_used") or detail.get("reviewer_route"),
              "verdict": detail.get("verdict")}
    findings = detail.get("finding_list")
    severities = [str((item or {}).get("severity") or "unknown") for item in findings if isinstance(item, dict)] \
        if isinstance(findings, list) else []
    if not severities and isinstance(detail.get("findings"), int):
        severities = ["unknown"] * max(0, detail["findings"])

    def count() -> None:
        REVIEW_VERDICTS.inc(**labels)
        for severity in severities:
            REVIEW_FINDINGS.inc(workflow=workflow, severity=severity)

    return count


def run_finished(run: Any, status: str) -> Callable[[], None] | None:
    run_id = str(_loaded(run, "id") or "")
    workflow = str(_loaded(run, "workflow_key") or _WORKFLOW_OF_RUN.get(run_id) or "unknown")
    return _phase_left(run_id, workflow, status, time.monotonic())


def forget_run(run_id: str) -> None:
    _PHASE_ENTERED.pop(run_id, None)


def _changed(row: Any, attribute: str) -> tuple[bool, Any]:
    history = inspect(row).attrs[attribute].history
    if history.added and history.deleted != history.added:
        return True, history.added[0]
    return False, None


def device_job_written(row: Any, *, new: bool) -> Callable[[], None] | None:
    job_id, now = str(row.id), time.monotonic()
    engine, profile = row.engine or "claude_code", row.profile
    from . import run_quality_metrics

    if new:
        if row.turn_state == TURN_RUNNING:
            return lambda: _TURN_ACCEPTED.put(job_id, now)
        return lambda: run_quality_metrics.job_queued(job_id)  # its wait for the device starts (accepted later)
    turn_changed, turn_state = _changed(row, "turn_state")
    status_changed, status = _changed(row, "status")
    disconnected, disconnected_at = _changed(row, "disconnected_at")
    counts: list[Callable[[], None]] = []
    outcome = turn_state if turn_changed and turn_state in TURN_ENDS else \
        status if status_changed and status in JOB_ENDS and job_id in _TURN_ACCEPTED else None
    if turn_changed and turn_state == TURN_RUNNING:
        counts.append(lambda: _TURN_ACCEPTED.put(job_id, now))
        counts.append(lambda: run_quality_metrics.job_accepted(job_id, engine))
    elif outcome is not None:
        model = row.model or row.turn_model or "default"
        effort = getattr(row, "turn_effort", None) or "default"

        def turn_ended() -> None:
            DEVICE_TURNS.inc(engine=engine, profile=profile, model=model, effort=effort, outcome=outcome)
            started = _TURN_ACCEPTED.pop(job_id, None)
            if started is not None:
                DEVICE_TURN_DURATION.observe(max(0.0, now - started), engine=engine, profile=profile)

        counts.append(turn_ended)
    if disconnected and disconnected_at is not None:
        counts.append(lambda: DEVICE_DISCONNECTS.inc(engine=engine))
    if not counts:
        return None

    def count() -> None:
        for one in counts:
            one()

    return count
