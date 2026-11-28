"""What runs now, held in memory: the live gauges of ``/metrics`` without a single database query (metrics never go
through the database)."""

from __future__ import annotations

import time
from collections import OrderedDict
from collections.abc import Callable, Iterable
from typing import Any

from sqlalchemy import inspect

from .metric_types import _escape, _number

KEEP_SECONDS = 24 * 3600.0
MAX_OBJECTS = 500
MAX_NAMES = 4000
ID_LENGTH = 12

FINISHED_RUNS = frozenset({"completed", "stopped", "failed"})
FINISHED_JOBS = frozenset({"failed", "device_lost", "closed", "rejected", "lost", "cancelled", "idle"})
TOKEN_TYPES = (("input", "tokens_in"), ("output", "tokens_out"), ("cache_read", "cache_read_tokens"),
               ("cache_write", "cache_creation_tokens"))
JOB_USAGE_KEYS = (("input", "input_tokens"), ("output", "output_tokens"),
                  ("cache_read", "cache_read_input_tokens"), ("cache_write", "cache_creation_input_tokens"))


def short(value: Any) -> str:
    return str(value or "")[:ID_LENGTH]


def held(row: Any, attribute: str) -> Any:
    return inspect(row).dict.get(attribute)


class _Bounded(OrderedDict[str, Any]):
    def __init__(self, limit: int) -> None:
        super().__init__()
        self.limit = limit

    def put(self, key: str, value: Any) -> None:
        self[key] = value
        self.move_to_end(key)
        while len(self) > self.limit:
            self.popitem(last=False)


class _Objects:
    def __init__(self) -> None:
        self.items: _Bounded = _Bounded(MAX_OBJECTS)

    def update(self, object_id: str, now: float, **fields: Any) -> dict[str, Any]:
        entry = dict(self.items.get(object_id) or {})
        entry.update({key: value for key, value in fields.items() if value is not None})
        entry["updated"] = now
        self.items.put(object_id, entry)
        return entry

    def get(self, object_id: str) -> dict[str, Any] | None:
        return self.items.get(object_id)

    def current(self, now: float) -> list[tuple[str, dict[str, Any]]]:
        for object_id in [key for key, entry in self.items.items() if now - entry["updated"] > KEEP_SECONDS]:
            self.items.pop(object_id, None)
        return list(self.items.items())

    def clear(self) -> None:
        self.items.clear()


RUNS = _Objects()
JOBS = _Objects()
SESSIONS = _Objects()
APPROVALS = _Objects()
WORKSPACE_NAMES = _Bounded(MAX_NAMES)  # project id -> name
EPIC_OF_ITEM = _Bounded(MAX_NAMES)  # work item id -> epic key (else parent key)
RUN_OF_SESSION = _Bounded(MAX_NAMES)  # session id -> (run id, role)
RUN_TOKENS = _Bounded(MAX_OBJECTS)  # run id -> {type: tokens} recorded in this process
ENGINE_OF_SESSION = _Bounded(MAX_NAMES)  # session id -> engine of its last recorded model call


def reset() -> None:
    for objects in (RUNS, JOBS, SESSIONS, APPROVALS):
        objects.clear()
    for remembered in (WORKSPACE_NAMES, EPIC_OF_ITEM, RUN_OF_SESSION, RUN_TOKENS, ENGINE_OF_SESSION):
        remembered.clear()


# ---- what the hook hands in (each returns what to apply on commit) ----------------------------------------------

def loaded(row: Any) -> None:
    table = getattr(type(row), "__tablename__", None)
    if table == "projects":
        _remember_workspace(row)
    elif table == "work_items":
        _remember_epic(row)


def _remember_workspace(row: Any) -> None:
    project_id, name = held(row, "id"), held(row, "name")
    if project_id and name:
        WORKSPACE_NAMES.put(str(project_id), str(name))


def _remember_epic(row: Any) -> None:
    item_id = held(row, "id")
    epic = held(row, "epic_key") or held(row, "parent_key")
    if item_id and epic:
        EPIC_OF_ITEM.put(str(item_id), str(epic))


def workspace_name(project_id: Any) -> str:
    if not project_id:
        return "none"
    return WORKSPACE_NAMES.get(str(project_id)) or str(project_id)


def written(row: Any, table: str, session: Any = None) -> Callable[[], None] | None:
    # Imported here: the handlers read this module's registers, so they cannot be imported at its top.
    from . import live_state_writes as writes

    if table == "projects":
        return lambda: _remember_workspace(row)
    if table == "work_items":
        return lambda: _remember_epic(row)
    if table == "workflow_runs":
        return writes.run_written(row)
    if table == "workflow_run_events":
        return writes.run_event_written(row, session)
    if table == "workflow_run_sessions":
        session_id, run_id, role = held(row, "session_id"), held(row, "run_id"), held(row, "role")
        if not (session_id and run_id):
            return None
        return lambda: RUN_OF_SESSION.put(str(session_id), (str(run_id), str(role or "main")))
    if table == "device_jobs":
        return writes.job_written(row)
    if table == "sessions":
        return writes.session_written(row)
    if table == "approvals":
        return writes.approval_written(row)
    if table == "usage_events":
        return writes.usage_written(row)
    return None


def approval_decided(approval_id: Any, status: str) -> None:
    if approval_id:
        APPROVALS.update(str(approval_id), time.time(), status=status)


def run_details(run_id: Any) -> dict[str, str]:
    run = RUNS.get(str(run_id or "")) or {}
    details = {"ticket": run.get("ticket"), "workflow": run.get("workflow"), "workspace": run.get("workspace"),
               "epic": EPIC_OF_ITEM.get(run.get("work_item") or ""), "phase": run.get("phase"),
               "size_class": run.get("size_class"), "workflow_version": run.get("workflow_version")}
    return {key: str(value) for key, value in details.items() if value}


def run_context(session_id: Any) -> dict[str, str] | None:
    link = RUN_OF_SESSION.get(str(session_id or ""))
    if link is None:
        return None
    return {"run": link[0], "role": link[1], **run_details(link[0])}


# ---- rendering ------------------------------------------------------------------------------------------------------


def gauge_lines(name: str, help_text: str, labels: tuple[str, ...],
                values: Iterable[tuple[tuple[Any, ...], float]]) -> list[str]:
    lines = [f"# HELP {name} {help_text}", f"# TYPE {name} gauge"]
    for key, value in sorted(values, key=lambda item: tuple(str(part) for part in item[0])):
        pairs = ",".join(f'{label}="{_escape(str(part)[:200])}"' for label, part in zip(labels, key, strict=True))
        lines.append(f"{name}{{{pairs}}} {_number(value)}")
    return lines


def _ticket(run_id: str, run: dict[str, Any]) -> str:
    return str(run.get("ticket") or f"run-{run_id[:8]}")



def _run_series(now: float) -> tuple[list[Any], ...]:
    runs = RUNS.current(now)
    state, started, finished, last_event, tokens, verdicts, findings, pipelines, unproven = ([] for _ in range(9))
    for run_id, run in runs:
        key = (short(run_id), _ticket(run_id, run))
        workflow = str(run.get("workflow") or "unknown")
        state.append(((*key, workflow, workspace_name(run.get("workspace")),
                       EPIC_OF_ITEM.get(run.get("work_item") or "") or "none", run.get("phase") or "none",
                       run.get("status") or "unknown", run.get("waiting_kind") or "none",
                       run.get("pause_reason") or "none"), run["updated"]))
        if run.get("started") is not None:
            started.append(((*key, workflow), run["started"]))
        if run.get("finished") is not None:
            finished.append(((*key, workflow), run["finished"]))
        if run.get("last_event") is not None:
            last_event.append(((*key, run["last_event"][0]), run["last_event"][1]))
        if run.get("review") is not None:
            phase, verdict, engine, model, count = run["review"]
            verdicts.append(((*key, phase, verdict, engine, model), run["updated"]))
            findings.append((key, count))
        if run.get("pipeline") is not None:
            pipelines.append(((*key, run["pipeline"][0]), run["updated"]))
            unproven.append((key, run["pipeline"][1]))
    for run_id, counted in list(RUN_TOKENS.items()):
        run = RUNS.get(run_id) or {}
        for kind, value in counted.items():
            tokens.append(((short(run_id), _ticket(run_id, run), str(run.get("workflow") or "unknown"), kind), value))
    return state, started, finished, last_event, tokens, verdicts, findings, pipelines, unproven


def _job_series(now: float) -> tuple[list[Any], list[Any], list[Any]]:
    jobs, job_turns, job_tokens = [], [], []
    for job_id, job in JOBS.current(now):
        link = RUN_OF_SESSION.get(str(job.get("session") or ""))
        run = (RUNS.get(link[0]) or {}) if link else {}
        ticket = _ticket(link[0], run) if link else "none"
        key = (short(job_id), ticket, str(job.get("engine") or "claude_code"))
        jobs.append(((*key, str(run.get("workflow") or "none"), str(run.get("phase") or "none"),
                      str(job.get("profile") or "unknown"), str(job.get("model") or "default"),
                      str(job.get("status") or "unknown"), str(job.get("turn_state") or "none")), job["updated"]))
        if job.get("turns") is not None:
            job_turns.append((key, int(job["turns"])))
        for kind, value in (job.get("tokens") or {}).items():
            job_tokens.append(((*key, kind), value))
    return jobs, job_turns, job_tokens


def render(now: float | None = None) -> list[str]:
    now = time.time() if now is None else now
    state, started, finished, last_event, tokens, verdicts, findings, pipelines, unproven = _run_series(now)
    jobs, job_turns, job_tokens = _job_series(now)

    sessions = [((short(object_id), str(entry.get("agent_type") or "diagnosis"), str(entry.get("status") or "unknown")),
                 entry["updated"]) for object_id, entry in SESSIONS.current(now)]
    approvals = [((short(object_id), str(entry.get("source") or "unknown"), str(entry.get("status") or "unknown")),
                  entry["updated"]) for object_id, entry in APPROVALS.current(now)]

    run_labels = ("run", "ticket")
    newest = "value: Unix seconds this process last saw it change; newest per id wins"
    return [
        *gauge_lines("octryx_workflow_run_state", f"Workflow runs changed in the last 24 h ({newest})",
                     (*run_labels, "workflow", "workspace", "epic", "phase", "status", "waiting_kind",
                      "pause_reason"), state),
        *gauge_lines("octryx_workflow_run_started_timestamp_seconds", "Start of each run (Unix seconds)",
                     (*run_labels, "workflow"), started),
        *gauge_lines("octryx_workflow_run_finished_timestamp_seconds", "When this process saw the run finish (Unix"
                     " seconds)", (*run_labels, "workflow"), finished),
        *gauge_lines("octryx_workflow_run_last_event_timestamp_seconds", "Newest event of each run (Unix seconds), by"
                     " its kind", (*run_labels, "event"), last_event),
        *gauge_lines("octryx_workflow_run_tokens", "Tokens of each run's sessions recorded in this process (sum over"
                     " processes)", (*run_labels, "workflow", "type"), tokens),
        *gauge_lines("octryx_review_last_verdict", f"Newest review verdict of each run ({newest})",
                     (*run_labels, "phase", "verdict", "engine", "model"), verdicts),
        *gauge_lines("octryx_review_last_findings", "Findings of the newest review of each run", run_labels, findings),
        *gauge_lines("octryx_pipeline_last_state", f"Newest pipeline state of each run ({newest})",
                     (*run_labels, "state"), pipelines),
        *gauge_lines("octryx_pipeline_unproven", "Unproven checks of the newest pipeline report of each run",
                     run_labels, unproven),
        *gauge_lines("octryx_device_job_state", f"Device jobs changed in the last 24 h, 1 series per job ({newest})",
                     ("job", "ticket", "engine", "workflow", "phase", "profile", "model", "status", "turn_state"),
                     jobs),
        *gauge_lines("octryx_device_job_turns", "Turns of each device job", ("job", "ticket", "engine"), job_turns),
        *gauge_lines("octryx_device_job_tokens", "Tokens of each device job's latest usage report",
                     ("job", "ticket", "engine", "type"), job_tokens),
        *gauge_lines("octryx_agent_session_state", f"Agent sessions changed in the last 24 h ({newest})",
                     ("session", "agent_type", "status"), sessions),
        *gauge_lines("octryx_approval_state", f"Approvals requested or decided in the last 24 h ({newest})",
                     ("approval", "source", "status"), approvals),
    ]
