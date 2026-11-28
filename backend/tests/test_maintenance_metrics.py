"""Maintenance metrics: findings per check, rule violations on main, run cost/duration/sessions by size class.
Counted at the event in this process; a run's cost is summed when its usage rows are inserted."""

from __future__ import annotations

import re
import uuid
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import event

from app.models import UsageEvent, WorkflowRun
from app.services.observability import agent_metrics, attribution, maintenance_metrics, run_quality_metrics
from app.time_utils import utc_now
from tests.observability_support import admin_user, call_as, session_for, workspace


@pytest.fixture(autouse=True)
def _empty_metrics():
    agent_metrics.reset()
    yield
    agent_metrics.reset()


def _series(name: str, **labels: str) -> float:
    metric = next(item for item in maintenance_metrics.METRICS if item.name == name)
    key = tuple(labels[label] for label in metric.labels)
    return metric.series.get(key, 0)


def _run(*events, run=None, workflow="story-delivery", run_id="r1"):
    for kind, detail in events:
        counted = maintenance_metrics.run_event(workflow, run_id, kind, detail, run=run)
        if counted is not None:
            counted()


def test_review_findings_are_raised_then_fixed_or_accepted():
    review = [("review_verdict", {"finding_list": [{"severity": "high"}, {"severity": "high"}, {"severity": "low"}]}),
              ("review_verdict", {"finding_list": [{"severity": "high"}]})]
    _run(*review)
    labels = {"workflow": "story-delivery", "check": "review"}
    assert _series("octryx_check_findings_total", **labels, severity="high", outcome="raised") == 3
    assert _series("octryx_check_findings_total", **labels, severity="high", outcome="fixed") == 1
    assert _series("octryx_check_findings_total", **labels, severity="low", outcome="fixed") == 1
    _run(("decision", {"kind": "confirmation", "subject": "decisions", "action": "confirmed"}))
    assert _series("octryx_check_findings_total", **labels, severity="high", outcome="accepted") == 1


def test_hands_on_waivers_code_style_and_what_reached_main():
    red = {"state": "red", "scenarios": [{"id": "S1", "passed": False}, {"id": "S2", "passed": False},
                                         {"id": "S3", "passed": True}]}
    _run(("hands_on_reported", red), ("hands_on_scenarios_waived", {"scenarios": ["S1", "S2"]}))
    hands_on = {"workflow": "story-delivery", "check": "hands_on", "severity": "error"}
    assert _series("octryx_check_findings_total", **hands_on, outcome="raised") == 2
    assert _series("octryx_check_findings_total", **hands_on, outcome="waived") == 2
    _run(("code_style_warnings", {"warnings": "a.dart:3: UI text in code: x [l10n_hardcoded_text]; b.dart:9: UI "
                                               "text in code: y [l10n_hardcoded_text]"}))
    assert _series("octryx_check_findings_total", workflow="story-delivery", check="code_style:l10n_hardcoded_text",
                   severity="warning", outcome="raised") == 2

    class Run:
        context = {"pipeline": {"code_style_errors": ["a.py:3: line has 200 characters [max_line_length]"],
                                "code_style_warnings": ["b.py: has 320 lines [max_lines_per_file]"]}}

    _run(("watch_condition_met", {"condition": "pr.merged", "source": "poll"}), run=Run())
    assert _series("octryx_main_rule_violations_total", workflow="story-delivery", rule="max_line_length",
                   severity="error") == 1
    assert _series("octryx_main_rule_violations_total", workflow="story-delivery", rule="max_lines_per_file",
                   severity="warning") == 1


def test_the_reference_runs_are_data_by_kind():
    plain = {"workflow": "bug-fix-reproduction", "size_class": "S", "kind": "plain"}
    assert _series("octryx_run_reference", **plain, measure="cost_usd") == 0.26
    assert _series("octryx_run_reference", **plain, measure="duration_seconds") == 73
    assert _series("octryx_run_reference", workflow="bug-fix-reproduction", size_class="S", kind="light_measured",
                   measure="cost_usd") == 0.92
    assert {labels[0] for labels in maintenance_metrics.REFERENCE.series} == {"bug-fix-reproduction"}


def test_an_escalated_run_counts_under_its_start_class_with_its_final_class():
    from types import SimpleNamespace

    maintenance_metrics.usage("r9", cost=0.4, list_cost=None, session_id="s1", engine="claude")
    run = SimpleNamespace(id="r9", workflow_key="story-delivery",
                          context={"size_class": {"class": "L", "initial": "M", "escalations": [{"from": "M"}]}})
    maintenance_metrics.run_finished(run, 600)()
    labels = ("story-delivery", "M", "L", "claude", "none", run_quality_metrics.prompt_version())
    counts, total = maintenance_metrics.RUN_COST.series[labels]
    assert counts[-1] == 1 and abs(total - 0.4) < 1e-9


def test_the_module_never_queries_the_database():
    source = Path(maintenance_metrics.__file__).read_text(encoding="utf-8")
    assert "select(" not in source and ".execute(" not in source and "session.get(" not in source


@pytest.mark.asyncio
async def test_a_finished_runs_cost_comes_from_its_inserted_usage_without_a_select(client, db):
    admin = await admin_user(db)
    project = await workspace(db, "Coffee")
    first, second = await session_for(db, admin, project=project), await session_for(db, admin, project=project)
    run = WorkflowRun(project_id=project.id, workflow_kind="phased", workflow_key="ticket-delivery", title="t",
                      requested_by=admin.id, context={"size_class": {"class": "S"}})
    db.add(run)
    await db.commit()
    run_id = run.id
    with attribution.scope(run=run_id, workflow="ticket-delivery", workspace=project.name):
        for session, cost in ((first, "0.10"), (second, "0.05"), (first, "0.02")):
            db.add(UsageEvent(id=str(uuid.uuid4()), session_id=session.id, user_id=admin.id, provider="bedrock",
                              model="claude-x", tokens_in=10, tokens_out=5, cost=Decimal(cost)))
        await db.commit()

    statements: list[str] = []
    engine = db.bind.sync_engine if hasattr(db.bind, "sync_engine") else db.get_bind().sync_engine

    def seen(_conn, _cursor, statement, *_args):
        statements.append(statement)

    event.listen(engine, "before_cursor_execute", seen)
    try:
        run = await db.get(WorkflowRun, run_id)
        run.status, run.completed_at = "completed", utc_now()
        await db.commit()
    finally:
        event.remove(engine, "before_cursor_execute", seen)
    assert any(re.search(r"\bUPDATE workflow_runs\b", text, re.I) for text in statements)
    assert not [text for text in statements if re.search(r"\bFROM (usage_events|sessions)\b", text, re.I)]

    text = (await call_as(client, "GET", "/metrics", admin)).text
    line = next(line for line in text.splitlines() if line.startswith('octryx_run_cost_usd_sum{workflow="ticket-delivery"'
                                                                      ',size_class="S"'))
    assert abs(float(line.rsplit(" ", 1)[1]) - 0.17) < 1e-9
    sessions = next(line for line in text.splitlines()
                    if line.startswith('octryx_run_sessions_sum{workflow="ticket-delivery",size_class="S"'))
    assert float(sessions.rsplit(" ", 1)[1]) == 2
    assert 'octryx_run_reference{workflow="bug-fix-reproduction",size_class="S",kind="plain",measure="cost_usd"} 0.26' \
        in text


@pytest.mark.asyncio
async def test_a_bug_in_delivered_work_is_an_escaped_defect_once(db):
    from app.services.secure_work.platform_items import create_platform_work_item
    from app.services.workflow_runs.bugs.escaped import EVENT_ESCAPED, record_escape
    from tests.services.secure_work.test_platform_work_items import _admin_and_project

    admin, project = await _admin_and_project(db)
    story = await create_platform_work_item(db, current_user=admin, project_id=project.id, title="S1 navigation",
                                            issue_type="story")
    db.add(WorkflowRun(project_id=project.id, workflow_kind="phased", workflow_key="story-delivery", title="s",
                       requested_by=admin.id, work_item_id=story.id, status="completed"))
    bug = await create_platform_work_item(db, current_user=admin, project_id=project.id, issue_type="bug",
                                          title="Grind starts at 0", description=f"Since {story.source_key} the "
                                          "grind value starts at 0.")
    unrelated = await create_platform_work_item(db, current_user=admin, project_id=project.id, issue_type="bug",
                                                title="Crash", description="No link.")
    await db.flush()
    run = WorkflowRun(project_id=project.id, workflow_kind="phased", workflow_key="bug-fix-reproduction", title="b",
                      requested_by=admin.id, work_item_id=bug.id, context={})
    db.add(run)
    await db.flush()
    recorded = []
    import app.services.workflow_runs.bugs.escaped as escaped_module

    original = escaped_module.record_event
    escaped_module.record_event = lambda db, run, kind, **kw: recorded.append((kind, kw["detail"]))
    try:
        assert await record_escape(db, run, bug) == {"key": story.source_key, "origin_workflow": "story-delivery"}
        assert await record_escape(db, run, bug) is None
        other = WorkflowRun(project_id=project.id, workflow_kind="phased", workflow_key="bug-fix-reproduction",
                            title="c", requested_by=admin.id, work_item_id=unrelated.id, context={})
        assert await record_escape(db, other, unrelated) is None
    finally:
        escaped_module.record_event = original
    assert recorded == [(EVENT_ESCAPED, {"key": story.source_key, "origin_workflow": "story-delivery"})]
    counted = maintenance_metrics.run_event("bug-fix-reproduction", "b1", EVENT_ESCAPED, recorded[0][1])
    counted()
    assert _series("octryx_item_escaped_defects_total", workflow="bug-fix-reproduction",
                   origin_workflow="story-delivery") == 1
