"""Maintenance metrics: what the platform's checks find and what becomes of it, what reaches main, and what a run of a
size class costs against reference runs."""

from __future__ import annotations

import json
import re
from collections import OrderedDict
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .metric_types import Counter, Gauge, Histogram, _Metric

COST_USD = (0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10, 20, 50)
RUN_SECONDS = (60, 300, 600, 1200, 1800, 3600, 7200, 14400, 43200, 86400)
SESSIONS = (1, 2, 3, 5, 8, 13, 21)
_REMEMBERED = 2000
_RULE = re.compile(r"\[([a-z_:.0-9-]+)\]")

# Size class it started in, the one it ended in, engine, and the workflow and prompt versions (before/after a change).
RUN_LABELS = ("workflow", "size_class", "final_class", "engine", "workflow_version", "prompt_version")

CHECK_FINDINGS = Counter("octryx_check_findings_total", "Findings of the platform's checks by workflow, check, "
                         "severity and outcome (raised, fixed, accepted, waived)",
                         ("workflow", "check", "severity", "outcome"))
MAIN_VIOLATIONS = Counter("octryx_main_rule_violations_total", "Code style findings in the last pipeline pass of "
                          "runs whose pull request merged, by workflow, rule and severity",
                          ("workflow", "rule", "severity"))
RUN_COST = Histogram("octryx_run_cost_usd", "API cost of a finished run in USD by workflow, size class and engine",
                     RUN_LABELS, COST_USD)
RUN_LIST_COST = Histogram("octryx_run_list_cost_usd", "Seat calls of a finished run at the API list price in USD",
                          RUN_LABELS, COST_USD)
RUN_DURATION = Histogram("octryx_run_duration_seconds_by_class", "Duration of a finished run by workflow, size "
                         "class and engine", RUN_LABELS, RUN_SECONDS)
RUN_SESSIONS = Histogram("octryx_run_sessions", "Sessions that made model calls in a finished run",
                         RUN_LABELS, SESSIONS)
ESCAPED = Counter("octryx_item_escaped_defects_total", "Bugs in work the platform delivered, by the bug flow's "
                  "workflow and the delivering workflow (recorded at the bug's intake)",
                  ("workflow", "origin_workflow"))
PRS_MERGED = Counter("octryx_pr_merged_total", "Pull requests of platform runs that merged, by workflow", ("workflow",))
PRS_REVERTED = Counter("octryx_pr_reverted_total", "Pull requests of platform runs that a merged pull request reverted,"
                       " by the run's workflow", ("workflow",))
REFERENCE = Gauge("octryx_run_reference", "Reference runs by workflow, size class, kind (plain, light_measured) and "
                  "measure (cost_usd, duration_seconds, sessions)", ("workflow", "size_class", "kind", "measure"))

METRICS: tuple[_Metric, ...] = (CHECK_FINDINGS, MAIN_VIOLATIONS, ESCAPED, PRS_MERGED, PRS_REVERTED, RUN_COST,
                                RUN_LIST_COST, RUN_DURATION,
                                RUN_SESSIONS, REFERENCE)

# Per run, in this process: open findings per check and what the run cost (bounded, oldest dropped).
_OPEN: OrderedDict[str, dict[str, dict[str, int]]] = OrderedDict()
_SPENT: OrderedDict[str, dict[str, Any]] = OrderedDict()


def _context(run: Any) -> dict[str, Any]:
    try:
        from sqlalchemy import inspect

        loaded = inspect(run).dict.get("context")
    except Exception:  # noqa: BLE001 - not an ORM row (tests): its plain attribute
        loaded = getattr(run, "context", None)
    return dict(loaded or {}) if isinstance(loaded, dict) else {}


def _bounded(store: OrderedDict, key: str, empty: Any) -> Any:
    value = store.setdefault(key, empty)
    store.move_to_end(key)
    while len(store) > _REMEMBERED:
        store.popitem(last=False)
    return value


def load_references(data: dict[str, Any] | None = None) -> None:
    if data is None:
        data = json.loads(Path(__file__).with_name("reference_runs.json").read_text(encoding="utf-8"))
    REFERENCE.series.clear()
    for item in data.get("references") or []:
        for measure in ("cost_usd", "duration_seconds", "sessions"):
            if isinstance(item.get(measure), int | float):
                REFERENCE.set(item[measure], workflow=item.get("workflow"), size_class=item.get("size_class"),
                              kind=item.get("kind"), measure=measure)


# ---- findings ---------------------------------------------------------------------------------------------------

def _severities(findings: list[Any]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in findings:
        severity = str(dict(item).get("severity") or "unknown") if isinstance(item, dict) else "unknown"
        counts[severity] = counts.get(severity, 0) + 1
    return counts


def _pass(workflow: str, run_id: str, check: str, now: dict[str, int]) -> Callable[[], None]:
    def count() -> None:
        before = _bounded(_OPEN, run_id, {}).get(check) or {}
        for severity, number in now.items():
            CHECK_FINDINGS.inc(number, workflow=workflow, check=check, severity=severity, outcome="raised")
        for severity, number in before.items():
            CHECK_FINDINGS.inc(max(number - now.get(severity, 0), 0), workflow=workflow, check=check,
                               severity=severity, outcome="fixed")
        _OPEN[run_id][check] = dict(now)

    return count


def _resolve(workflow: str, run_id: str, check: str, outcome: str, number: int | None = None) -> Callable[[], None]:
    def count() -> None:
        open_now = _bounded(_OPEN, run_id, {}).get(check) or {}
        for severity, open_count in open_now.items():
            CHECK_FINDINGS.inc(open_count if number is None else min(number, open_count), workflow=workflow,
                               check=check, severity=severity, outcome=outcome)
        _OPEN[run_id].pop(check, None)

    return count


def _style_rules(text: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for rule in _RULE.findall(text):
        counts[rule] = counts.get(rule, 0) + 1
    return counts


def run_event(workflow: str, run_id: str, kind: str, detail: dict[str, Any],
              run: Any = None) -> Callable[[], None] | None:
    if kind == "pr_reverted":
        return lambda: PRS_REVERTED.inc(workflow=workflow)
    if kind == "watch_condition_met" and detail.get("condition") == "pr.merged" and run is None:
        return lambda: PRS_MERGED.inc(workflow=workflow)
    if kind == "bug_escaped_from":
        origin = str(detail.get("origin_workflow") or "unknown")
        return lambda: ESCAPED.inc(workflow=workflow, origin_workflow=origin)
    if kind == "review_verdict":
        return _pass(workflow, run_id, "review", _severities(list(detail.get("finding_list") or [])))
    if kind == "hands_on_reported" and detail.get("state") in ("red", "green"):
        failed = [item for item in detail.get("scenarios") or [] if isinstance(item, dict) and not item.get("passed")]
        return _pass(workflow, run_id, "hands_on", {"error": len(failed)} if failed else {})
    if kind == "hands_on_scenarios_waived":
        return _resolve(workflow, run_id, "hands_on", "waived", len(list(detail.get("scenarios") or [])))
    if kind == "decision" and detail.get("subject") == "decisions" and detail.get("action") == "confirmed":
        return _resolve(workflow, run_id, "review", "accepted")
    if kind == "code_style_warnings":
        rules = _style_rules(str(detail.get("warnings") or ""))
        counts = [(f"code_style:{rule}", number) for rule, number in rules.items()]

        def count() -> None:
            for check, number in counts:
                CHECK_FINDINGS.inc(number, workflow=workflow, check=check, severity="warning", outcome="raised")

        return count
    if kind == "watch_condition_met" and detail.get("condition") == "pr.merged" and run is not None:
        pipeline = dict(_context(run).get("pipeline") or {})
        found = [("error", text) for text in pipeline.get("code_style_errors") or []] + [
            ("warning", text) for text in pipeline.get("code_style_warnings") or []]
        counts: dict[tuple[str, str], int] = {}
        for severity, text in found:
            for rule, number in _style_rules(str(text)).items():
                counts[(rule, severity)] = counts.get((rule, severity), 0) + number

        def merged() -> None:
            PRS_MERGED.inc(workflow=workflow)
            for (rule, severity), number in counts.items():
                MAIN_VIOLATIONS.inc(number, workflow=workflow, rule=rule, severity=severity)
            _OPEN.pop(run_id, None)

        return merged
    return None


# ---- cost per run -----------------------------------------------------------------------------------------------

def usage(run_id: str, *, cost: float, list_cost: float | None, session_id: str, engine: str) -> None:
    if not run_id:
        return
    spent = _bounded(_SPENT, run_id, {"cost": 0.0, "list_cost": 0.0, "sessions": set(), "engine": engine})
    spent["cost"] += float(cost or 0)
    spent["list_cost"] += float(list_cost or 0)
    if session_id:
        spent["sessions"].add(session_id)
    spent["engine"] = spent.get("engine") or engine


def run_finished(run: Any, seconds: float | None) -> Callable[[], None]:
    run_id, workflow = str(run.id), str(run.workflow_key or "")
    # Keyed by the class the run STARTED in: an escalation M → L is the platform's extra cost
    # and must show against the start class's reference; the class it ended in is its own label.
    entry = dict(_context(run).get("size_class") or {})
    size_class = str(entry.get("initial") or entry.get("class") or "none")
    final_class = str(entry.get("class") or size_class)
    # Before/after a workflow or prompt change : both are labels.
    workflow_version = str(getattr(run, "workflow_version", "") or "none")
    from .run_quality_metrics import prompt_version

    def count() -> None:
        spent = _SPENT.pop(run_id, None) or {"cost": 0.0, "list_cost": 0.0, "sessions": set(), "engine": "none"}
        labels = {"workflow": workflow, "size_class": size_class, "final_class": final_class,
                  "engine": spent.get("engine") or "none", "workflow_version": workflow_version,
                  "prompt_version": prompt_version()}
        RUN_COST.observe(spent["cost"], **labels)
        if spent["list_cost"]:
            RUN_LIST_COST.observe(spent["list_cost"], **labels)
        if seconds is not None:
            RUN_DURATION.observe(seconds, **labels)
        RUN_SESSIONS.observe(len(spent["sessions"]), **labels)
        _OPEN.pop(run_id, None)

    return count


def reset() -> None:
    for metric in METRICS:
        metric.series.clear()
    _OPEN.clear()
    _SPENT.clear()
    load_references()


load_references()

__all__ = ["METRICS", "load_references", "reset", "run_event", "run_finished", "usage"]
