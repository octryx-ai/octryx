"""Agent metrics for Prometheus and Grafana: counters and histograms of what agents do (``octryx_*``)."""

from __future__ import annotations

import contextvars
import hashlib
from collections.abc import Callable, Iterable, Iterator
from contextlib import contextmanager
from datetime import datetime
from typing import Any

from sqlalchemy import event, inspect
from sqlalchemy.orm import Mapper
from sqlalchemy.orm import Session as OrmSession

from . import (
    attribution,
    check_proposal_metrics,
    correction_metrics,
    hands_on_metrics,
    knowledge_metrics,
    live_state,
    maintenance_metrics,
    platform_metrics,
    review_bot_metrics,
    run_quality_metrics,
    workflow_metrics,
)
from .metric_types import OTHER, Counter, Histogram, _Metric
from .token_profile import metrics as token_profile_metrics

_PENDING = "octryx_metrics_pending"

ATTRIBUTED_SERIES = 2000
LLM_SECONDS = (0.25, 0.5, 1, 2.5, 5, 10, 20, 30, 60, 120, 300)
TOOL_SECONDS = (0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30, 60, 300)
RUN_SECONDS = (10, 30, 60, 300, 900, 1800, 3600, 7200, 21600, 86400)
APPROVAL_SECONDS = (10, 60, 300, 900, 3600, 14400, 86400, 259200)

FINISHED_RUN_STATUSES = frozenset({"completed", "stopped", "failed"})

# Which way a model call went (label ``route``): the person's seat through the gateway, the independent review, an
# engine runtime chain, or a governed platform model.
ROUTE_GATEWAY, ROUTE_REVIEW, ROUTE_ENGINE_CHAIN, ROUTE_GOVERNED = ("gateway", "review", "engine_chain", "governed")
SEAT_COST_SOURCE = "seat_subscription"
REVIEW_DISPATCH_OWNER = "workflow_run_review"
ENGINE_CHAIN_DISPATCH_OWNER = "engine_runtime_chain"
# The seat call being recorded (route, seconds): set by the seat recorder around its write.
_SEAT_CALL: contextvars.ContextVar[tuple[str, float | None] | None] = contextvars.ContextVar(
    "octryx_seat_call", default=None)


LLM_REQUESTS = Counter("octryx_llm_requests_total", "LLM requests by provider, model, route (gateway, review,"
                       " engine_chain, governed) and outcome (ok, error, timeout, cancelled)",
                       ("provider", "model", "route", "outcome"))
LLM_SECONDS_METRIC = Histogram("octryx_llm_request_duration_seconds", "LLM request duration in seconds",
                               ("provider", "model", "route"), LLM_SECONDS)
LLM_TOKENS = Counter("octryx_llm_tokens_total", "LLM tokens by provider, model, route, type (input, output,"
                     " cache_read, cache_write), engine (claude_code, codex, governed), role (work, review, spec,"
                     " engine_chain, none) and Workspace (no epic: it grows with every epic; per epic see the"
                     " run gauges)",
                     ("provider", "model", "route", "type", "engine", "role", "workspace"),
                     max_series=ATTRIBUTED_SERIES)
LLM_USAGE_EVENTS = Counter("octryx_llm_usage_events_total", "Recorded model calls (usage rows; a review may record"
                           " one row for several calls) by engine, model, role and Workspace",
                           ("engine", "model", "role", "workspace"), max_series=ATTRIBUTED_SERIES)
UNATTRIBUTED = Counter("octryx_metrics_unattributed_total", "Model calls counted without a run context (no run, or"
                       " none known in this process), by source", ("source",))
LLM_COST = Counter("octryx_llm_cost_usd_total", "Attributed LLM cost in USD by provider, model and route",
                   ("provider", "model", "route"))
SEAT_USAGE_LIST_USD = Counter(
    "octryx_seat_usage_list_usd_total", "What the seat calls would have cost through the API at list price (USD; the"
    " seat's API equivalent, never part of octryx_llm_cost_usd_total), by seat (a short pseudonym of the person's"
    " seat account), provider and model", ("seat", "provider", "model"))
SEAT_USAGE_UNPRICED = Counter(
    "octryx_seat_usage_unpriced_total", "Seat calls whose model has no list price (no API equivalent), by provider and"
    " model", ("provider", "model"))
TOOL_CALLS = Counter("octryx_tool_calls_total", "Agent tool calls by tool and status", ("tool", "status"))
TOOL_DURATION = Histogram("octryx_tool_call_duration_seconds", "Agent tool call duration in seconds", ("tool",),
                          TOOL_SECONDS)
TURNS = Counter("octryx_agent_turns_total", "Agent turns by agent (agent, workflow or client) and outcome",
                ("agent", "outcome"))
SESSIONS = Counter("octryx_agent_sessions_started_total", "Agent sessions started by agent type, origin and kind"
                   " (main, sub_agent)", ("agent_type", "origin", "kind"))
RUNS_STARTED = Counter("octryx_workflow_runs_started_total", "Workflow runs started by workflow and Workspace",
                       ("workflow", "workspace"))
RUNS_FINISHED = Counter("octryx_workflow_runs_finished_total", "Workflow runs finished by workflow, Workspace and"
                        " status (completed, stopped, failed)", ("workflow", "workspace", "status"))
RUN_DURATION = Histogram("octryx_workflow_run_duration_seconds", "Workflow run duration from start to finish in"
                         " seconds", ("workflow", "status"), RUN_SECONDS)
APPROVALS_REQUESTED = Counter("octryx_approvals_requested_total", "Approvals requested by what asks (session,"
                              " task_run, review)", ("source",))
APPROVALS_DECIDED = Counter("octryx_approvals_decided_total", "Approvals decided by outcome", ("status",))
APPROVAL_WAIT = Histogram("octryx_approval_wait_seconds", "Time from approval request to decision in seconds",
                          ("status",), APPROVAL_SECONDS)

METRICS: tuple[_Metric, ...] = (LLM_REQUESTS, LLM_SECONDS_METRIC, LLM_TOKENS, LLM_COST, TOOL_CALLS, TOOL_DURATION,
                                TURNS, SESSIONS, RUNS_STARTED, RUNS_FINISHED, RUN_DURATION, APPROVALS_REQUESTED,
                                APPROVALS_DECIDED, APPROVAL_WAIT, SEAT_USAGE_LIST_USD,
                                SEAT_USAGE_UNPRICED, LLM_USAGE_EVENTS, UNATTRIBUTED,
                                *workflow_metrics.METRICS, *platform_metrics.METRICS, *knowledge_metrics.METRICS,
                                *review_bot_metrics.METRICS, *maintenance_metrics.METRICS, *hands_on_metrics.METRICS,
                                *token_profile_metrics.METRICS, *run_quality_metrics.METRICS,
                                *correction_metrics.METRICS, *check_proposal_metrics.METRICS)


def reset() -> None:
    for metric in METRICS:
        metric.series.clear()
    workflow_metrics.reset()
    run_quality_metrics.reset()
    platform_metrics.reset()
    knowledge_metrics.reset()
    review_bot_metrics.reset()
    hands_on_metrics.reset()
    check_proposal_metrics.reset()
    maintenance_metrics.reset()
    token_profile_metrics.reset()
    correction_metrics.reset()
    live_state.reset()


# ---- recorders ------------------------------------------------------------------------------------------------------

def record_llm_request(provider: str, model: str, outcome: str, seconds: float, route: str = ROUTE_GOVERNED) -> None:
    LLM_REQUESTS.inc(provider=provider, model=model, route=route, outcome=outcome)
    LLM_SECONDS_METRIC.observe(seconds, provider=provider, model=model, route=route)


@contextmanager
def seat_call(route: str, seconds: float | None) -> Iterator[None]:
    token = _SEAT_CALL.set((route, seconds))
    try:
        yield
    finally:
        _SEAT_CALL.reset(token)


def seat_pseudonym(user_id: Any, provider: Any) -> str:
    return hashlib.sha256(f"{user_id or ''}:{provider or ''}".encode()).hexdigest()[:10]


def usage_route(row: Any) -> str:
    if row.dispatch_owner == REVIEW_DISPATCH_OWNER:
        return ROUTE_REVIEW
    if row.dispatch_owner == ENGINE_CHAIN_DISPATCH_OWNER:
        return ROUTE_ENGINE_CHAIN
    if row.cost_source == SEAT_COST_SOURCE:
        seat = _SEAT_CALL.get()
        return seat[0] if seat else ROUTE_GATEWAY
    return ROUTE_GOVERNED


ENGINE_CLAUDE_CODE, ENGINE_CODEX, ENGINE_GOVERNED = "claude_code", "codex", "governed"
ROLE_WORK, ROLE_REVIEW, ROLE_SPEC, ROLE_ENGINE_CHAIN, ROLE_NONE = "work", "review", "spec", "engine_chain", "none"
SPEC_WORKFLOWS = frozenset({"spec-writing"})
_ENGINE_OF_PROVIDER = {"anthropic": ENGINE_CLAUDE_CODE, "anthropic_seat": ENGINE_CLAUDE_CODE,
                       "claude_code": ENGINE_CLAUDE_CODE, "openai": ENGINE_CODEX, "openai_codex_seat": ENGINE_CODEX,
                       "codex": ENGINE_CODEX}


def usage_engine(provider: str | None) -> str:
    return _ENGINE_OF_PROVIDER.get(str(provider or "").lower(), ENGINE_GOVERNED)


def usage_run(row: Any) -> str:
    context = dict(attribution.of(row) or attribution.current() or {})
    return str(context.get("run") or dict(live_state.run_context(row.session_id) or {}).get("run") or "")


def usage_attribution(row: Any, route: str, session: Any = None) -> dict[str, str]:
    context = dict(attribution.of(row) or attribution.current() or {})
    if not context.get("run"):
        context.update(live_state.run_context(row.session_id) or {})
    elif not (context.get("epic") and context.get("workflow") and context.get("workspace")):
        known = live_state.run_details(context["run"])
        context = {**known, **context}
    workflow, role = context.get("workflow") or "", context.get("role") or ""
    if route == ROUTE_REVIEW or role in ("review", "reviewer"):
        role = ROLE_REVIEW
    elif route == ROUTE_ENGINE_CHAIN:
        role = ROLE_ENGINE_CHAIN
    elif not context.get("run"):
        role = ROLE_NONE
    elif workflow in SPEC_WORKFLOWS:
        role = ROLE_SPEC
    else:
        role = ROLE_WORK
    workspace = context.get("workspace") or _session_workspace(session, row.session_id)
    return {"engine": usage_engine(row.provider), "role": role, "workspace": workspace or "none"}


def _tool_context(session: Any, session_id: Any) -> tuple[dict[str, str], str]:
    context = dict(attribution.current() or {})
    if context.get("run"):
        context = {**live_state.run_details(context["run"]), **context}
    else:
        context.update(live_state.run_context(session_id) or {})
    if not context.get("workspace"):
        context["workspace"] = _session_workspace(session, session_id) or ""
    return context, live_state.ENGINE_OF_SESSION.get(str(session_id or "")) or ENGINE_GOVERNED


def _session_workspace(session: Any, session_id: Any) -> str | None:
    if session is None or not session_id:
        return None
    from ...models import Session

    chat = session.identity_map.get(session.identity_key(Session, session_id))
    return str(chat.__dict__.get("project_id") or "") or None if chat is not None else None


def _seconds(start: datetime | None, end: datetime | None) -> float | None:
    if start is None or end is None:
        return None
    if (start.tzinfo is None) != (end.tzinfo is None):
        start, end = start.replace(tzinfo=None), end.replace(tzinfo=None)
    return max(0.0, (end - start).total_seconds())


def approval_decided(approval: Any) -> Callable[[], None]:
    status, wait = str(approval.status or "unknown"), _seconds(approval.created_at, approval.resolved_at)
    approval_id = approval.id

    def count() -> None:
        live_state.approval_decided(approval_id, status)
        APPROVALS_DECIDED.inc(status=status)
        if wait is not None:
            APPROVAL_WAIT.observe(wait, status=status)

    return count


def on_commit(db: Any, count: Callable[[], None]) -> None:
    session = getattr(db, "sync_session", db)
    session.info.setdefault(_PENDING, []).append(count)


# ---- ORM hook -------------------------------------------------------------------------------------------------------

def _changed_to(row: Any, attribute: str) -> Any:
    history = inspect(row).attrs[attribute].history
    return history.added[0] if history.added and history.deleted != history.added else None


def _on_insert(session: OrmSession, row: Any, table: str) -> Callable[[], None] | None:
    if table == "usage_events":
        provider, model, route = row.provider, row.model, usage_route(row)
        tokens = {"input": row.tokens_in, "output": row.tokens_out, "cache_read": row.cache_read_tokens,
                  "cache_write": row.cache_creation_tokens}
        cost = float(row.cost or 0)
        # Seat calls never pass the provider wrapper: their recorded usage is the request (ok); a duration comes
        # with the seat call being recorded.
        seat = row.cost_source == SEAT_COST_SOURCE
        seconds = (_SEAT_CALL.get() or (route, None))[1] if seat else None

        who = usage_attribution(row, route, session)
        session_id = str(row.session_id or "")
        run_id = usage_run(row)
        list_cost = None if row.list_cost is None else float(row.list_cost)
        equivalent = None if row.list_cost is None else float(row.list_cost)
        seat_key = seat_pseudonym(row.user_id, provider) if seat else ""

        def count() -> None:
            if session_id:
                live_state.ENGINE_OF_SESSION.put(session_id, who["engine"])
            # The run's cost and sessions, summed at the insert (maintenance metrics; no query at the run's end).
            maintenance_metrics.usage(run_id, cost=cost, list_cost=list_cost, session_id=session_id,
                                      engine=who["engine"])
            LLM_USAGE_EVENTS.inc(model=model, **who)
            if who["role"] == ROLE_NONE:
                UNATTRIBUTED.inc(source="usage")
            for kind, value in tokens.items():
                LLM_TOKENS.inc(int(value or 0), provider=provider, model=model, route=route, type=kind, **who)
            LLM_COST.inc(cost, provider=provider, model=model, route=route)
            if seat:
                if equivalent is None:
                    SEAT_USAGE_UNPRICED.inc(provider=provider, model=model)
                else:
                    SEAT_USAGE_LIST_USD.inc(equivalent, seat=seat_key, provider=provider, model=model)
                LLM_REQUESTS.inc(provider=provider, model=model, route=route, outcome="ok")
                if seconds is not None:
                    LLM_SECONDS_METRIC.observe(seconds, provider=provider, model=model, route=route)

        return count
    if table == "workflow_run_events":
        return workflow_metrics.run_event(session, row)
    if table == "device_jobs":
        return workflow_metrics.device_job_written(row, new=True)
    if table == "tool_calls":
        tool, status, duration = row.tool_name, row.status or "success", row.duration_ms
        lookup = knowledge_metrics.tool_call(row, *_tool_context(session, row.session_id))

        def count() -> None:
            TOOL_CALLS.inc(tool=tool, status=status)
            if duration is not None:
                TOOL_DURATION.observe(duration / 1000, tool=tool)
            if lookup is not None:
                lookup()

        return count
    if table == "turn_trace_summaries":
        agent, outcome = row.agent_label, row.outcome
        return lambda: TURNS.inc(agent=agent, outcome=outcome)
    if table == "sessions":
        labels = {"agent_type": row.agent_type or "diagnosis", "origin": row.origin or "chat",
                  "kind": "sub_agent" if row.parent_session_id else "main"}
        return lambda: SESSIONS.inc(**labels)
    if table == "approvals":
        source = "session" if row.session_id else "task_run" if row.task_run_id else "review"
        return lambda: APPROVALS_REQUESTED.inc(source=source)
    if table == "workflow_runs":
        workflow_metrics.remember_run(row)
        workflow, workspace = row.workflow_key, row.project_id or "none"
        return lambda: RUNS_STARTED.inc(workflow=workflow, workspace=workspace)
    return None


def _on_update(_session: OrmSession, row: Any, table: str) -> Callable[[], None] | None:
    if table == "device_jobs":
        return workflow_metrics.device_job_written(row, new=False)
    if table != "workflow_runs":
        return None
    workflow_metrics.remember_run(row)
    status = _changed_to(row, "status")
    if status not in FINISHED_RUN_STATUSES:
        return None
    workflow, workspace, run_id = row.workflow_key, row.project_id or "none", str(row.id)
    seconds = _seconds(row.created_at, row.completed_at or row.updated_at)
    phase_left = workflow_metrics.run_finished(row, status)
    by_class = maintenance_metrics.run_finished(row, seconds)

    def count() -> None:
        RUNS_FINISHED.inc(workflow=workflow, workspace=workspace, status=status)
        if seconds is not None:
            RUN_DURATION.observe(seconds, workflow=workflow, status=status)
        if phase_left is not None:
            phase_left()
        by_class()
        workflow_metrics.forget_run(run_id)

    return count


def _collect(session: OrmSession, rows: Iterable[Any], handler: Callable[[OrmSession, Any, str], Any]) -> None:
    for row in rows:
        table = getattr(type(row), "__tablename__", None)
        if table is None:
            continue
        try:
            count = handler(session, row, table)
        except Exception:  # noqa: BLE001 - counting never breaks a write
            continue
        if count is not None:
            session.info.setdefault(_PENDING, []).append(count)


def _live(session: OrmSession, row: Any, table: str) -> Callable[[], None] | None:
    return live_state.written(row, table, session)


def _after_flush(session: OrmSession, _context: Any) -> None:
    _collect(session, session.new, _on_insert)
    _collect(session, session.dirty, _on_update)
    _collect(session, list(session.new) + list(session.dirty), _live)
    _collect(session, session.new, lambda _session, row, table: platform_metrics.written(row, table, True))
    _collect(session, session.dirty, lambda _session, row, table: platform_metrics.written(row, table, False))


def _on_load(row: Any, _context: Any) -> None:
    try:
        live_state.loaded(row)
    except Exception:  # noqa: BLE001, S110 - remembering a name never breaks a load
        pass


def _after_commit(session: OrmSession) -> None:
    for count in session.info.pop(_PENDING, None) or ():
        try:
            count()
        except Exception:  # noqa: BLE001, S112 - a broken count must not break the commit
            continue


def _after_transaction_end(session: OrmSession, transaction: Any) -> None:
    if transaction.parent is None:  # the outer transaction ended without commit: nothing of it happened
        session.info.pop(_PENDING, None)


def install() -> None:
    if not event.contains(OrmSession, "after_flush", _after_flush):
        event.listen(OrmSession, "after_flush", _after_flush)
        event.listen(OrmSession, "after_commit", _after_commit)
        event.listen(OrmSession, "after_transaction_end", _after_transaction_end)
    if not event.contains(Mapper, "load", _on_load):  # the Workspaces and work items requests load anyway
        event.listen(Mapper, "load", _on_load)


# ---- rendering ------------------------------------------------------------------------------------------------------

def _workspace_renamer(metric: _Metric) -> Callable[[tuple[str, ...]], tuple[str, ...]]:
    if "workspace" not in metric.labels:
        return lambda key: key
    index = metric.labels.index("workspace")

    def rename(key: tuple[str, ...]) -> tuple[str, ...]:
        value = key[index]
        name = value if value in ("none", OTHER, "unknown") else live_state.workspace_name(value)
        return (*key[:index], name, *key[index + 1:])

    return rename


def render() -> list[str]:
    lines: list[str] = []
    for metric in METRICS:
        lines.extend(metric.render(_workspace_renamer(metric)))
    return lines + live_state.render()
