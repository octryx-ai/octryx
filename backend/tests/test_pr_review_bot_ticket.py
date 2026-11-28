"""PR review bot: the pull request's ticket and its acceptance criteria."""

from __future__ import annotations

import pytest

from app.models import WorkflowRun, WorkItem
from app.models.runtime.secure_work import WorkItemSyncConfig
from app.services.pr_review_bot import ticket_context
from app.services.pr_review_bot.events import pull_request_event
from app.services.pr_review_bot.render import build_post
from app.services.pr_review_bot.starter import TRIGGER_WEBHOOK, start_review
from app.services.workflow_runs.review.runner import run_due_reviews
from app.services.workflow_runs.review.verdict import MAX_ACCEPTANCE, parse_verdict
from tests.pr_review_bot_flow_support import HEADERS, REVIEW, _origin, _payload, _tools, _workspace
from tests.scripted_pool_support import scripted_pool  # noqa: F401 - fixture
from tests.workflow_run_review_support import ScriptedReviewer

pytestmark = pytest.mark.usefixtures("scripted_pool")


def test_key_shaped_words_come_from_branch_title_and_commits_in_that_order():
    assert ticket_context.candidates("feature/ocx-12-totals", "Totals for OCX-13 (UTF-8 safe)", [
        "Fix rounding\n\nOctryx-Run: CAF-7", "OCX-12 again"]) == ["OCX-12", "OCX-13", "UTF-8", "CAF-7"]


async def _run(db, project_id: str, branch: str, title: str = "t") -> WorkflowRun:
    from app.services.pr_review_bot.bot_user import ensure_review_bot_user

    owner = await ensure_review_bot_user(db, project_id)
    run = WorkflowRun(project_id=project_id, workflow_kind="phased", workflow_key="pr-review-bot", title="bot",
                      requested_by=owner.id, repository="github:acme/pay", branch=branch,
                      context={"pr_review": {"source_branch": branch, "title": title}})
    db.add(run)
    await db.flush()
    return run


async def test_a_workspace_work_item_named_in_the_branch_is_linked_and_utf_8_is_not(db):
    project_id, _record, _hook = await _workspace(db)
    item = WorkItem(source_type="platform", source_instance="octryx", source_key="OCX-12", source_project_key="OE",
                    title="Totals round half up", project_id=project_id, work_state="development")
    db.add(item)
    run = await _run(db, project_id, "feature/ocx-12-totals", "UTF-8 safe totals")
    found = await ticket_context.link_ticket(db, run, run.context["pr_review"], "", "", "")
    assert found == {"key": "OCX-12", "source": "workspace", "title": "Totals round half up"}
    assert run.work_item_id == item.id
    other = await _run(db, project_id, "feature/utf-8-fix", "ISO-27001 notes")
    assert await ticket_context.link_ticket(db, other, other.context["pr_review"], "", "", "") == {}
    assert other.work_item_id is None


async def test_a_key_of_a_connected_jira_project_is_read_and_stored_like_the_sync(db, monkeypatch):
    project_id, _record, _hook = await _workspace(db)
    from tests.phased_workflow_fixtures import admin_user

    owner = await admin_user(db)
    db.add(WorkItemSyncConfig(project_id=project_id, source_type="jira", is_active=True, name="Jira CAF",
                              filters_json={"project_keys": ["CAF"]}, created_by=owner.id))
    await db.flush()
    asked = []

    async def dispatch(_db, _run, tool, arguments, *, capability_class, **_):
        from app.services.workflow_runs.platform.dispatch import SUCCEEDED, ToolOutcome

        asked.append((tool, arguments, capability_class))
        return ToolOutcome(SUCCEEDED, {"summary": "Grind setting starts at 15", "id": "10077",
                                       "description": "AC1: the grinder starts at 15.\nAC2: 1-40 only."})

    monkeypatch.setattr("app.services.workflow_runs.platform.dispatch.dispatch_tool", dispatch)
    run = await _run(db, project_id, "feature/grind", "CAF-7: grind setting")
    found = await ticket_context.link_ticket(db, run, run.context["pr_review"], "", "", "")
    assert asked == [("get_jira_ticket", {"ticket_id": "CAF-7"}, "read_only")]
    assert found["key"] == "CAF-7" and found["source"] == "jira"
    item = await db.get(WorkItem, run.work_item_id)
    assert (item.source_type, item.title) == ("jira", "Grind setting starts at 15") and "AC2" in item.description


def test_acceptance_is_optional_bounded_and_never_changes_the_verdict():
    rows = [{"criterion": "AC1 " + "x" * 400, "status": "covered", "evidence": "pay/bulk.py:13"},
            {"criterion": "AC2", "status": "MISSING", "evidence": ""},
            {"criterion": "AC3", "status": "done"},
            *({"criterion": f"AC{n}", "status": "partial"} for n in range(4, 50))]
    verdict = parse_verdict({"verdict": "pass", "summary": "ok", "findings": [], "acceptance": rows})
    assert verdict.passed
    assert len(verdict.acceptance) == MAX_ACCEPTANCE and len(verdict.acceptance[0][0]) == 300
    assert verdict.acceptance[1] == ("AC2", "missing", "") and "AC3" not in [row[0] for row in verdict.acceptance]
    assert parse_verdict({"verdict": "pass", "summary": "", "findings": [], "acceptance": "all fine"}).acceptance == ()
    assert "acceptance" not in parse_verdict({"verdict": "pass", "summary": "", "findings": []}).to_dict()


def test_the_summary_shows_the_acceptance_table_and_the_footer_the_ticket():
    post = build_post({"verdict": "pass", "summary": "Fine.", "findings": [], "acceptance": [
        {"criterion": "Exactly 10 items get 5 %", "status": "covered", "evidence": "pay/bulk.py:13"},
        {"criterion": "An empty order averages 0", "status": "missing", "evidence": "no guard"}]}, {},
        provider="github", facts={"sha": "a" * 40, "ticket": {"key": "OCX-12", "title": "Bulk discount"}})
    assert "| Exactly 10 items get 5 % | ✅ covered | pay/bulk.py:13 |" in post.summary
    assert "| An empty order averages 0 | ❌ missing | no guard |" in post.summary
    assert "ticket OCX-12 (Bulk discount)" in post.summary and post.state == "success"


async def test_the_bot_reviews_with_the_ticket_and_asks_for_the_acceptance_table(db, monkeypatch, tmp_path):
    clone, head = _origin(tmp_path)
    tools = _tools(monkeypatch, clone)
    project_id, _record, _hook = await _workspace(db)
    db.add(WorkItem(source_type="platform", source_instance="octryx", source_key="PAY-1", source_project_key="PAY",
                    title="Totals round half up", description="AC1: 2.5 rounds to 3.", project_id=project_id,
                    work_state="development"))
    await db.flush()
    await start_review(db, project_id, pull_request_event(_payload(head), HEADERS), trigger=TRIGGER_WEBHOOK)
    reviewer = ScriptedReviewer({**REVIEW, "acceptance": [
        {"criterion": "2.5 rounds to 3", "status": "missing", "evidence": "round() rounds half to even"}]})
    assert await run_due_reviews(db, model_factory=reviewer.factory) == 1
    system, task = reviewer.tasks[0]
    assert '"acceptance"' in system and "Totals round half up" in task and "AC1: 2.5 rounds to 3." in task
    posted = [call[1] for call in tools.calls if call[0] == "post_github_pull_request_review"][-1]
    assert "<<<acceptance criteria of PAY-1" in task and "AC1: 2.5 rounds to 3." in task
    assert "| AC1: 2.5 rounds to 3. | ❌ missing | round() rounds half to even |" in posted["summary"]
    assert "ticket PAY-1 (Totals round half up)" in posted["summary"]


OCX_79 = """Bulk savings shown on the order.
AC1: bulk_savings returns subtotal minus bulk_total.
AC2: an empty order saves 0.
AC3: the savings are rounded to 2 decimal places."""


def test_acceptance_criteria_are_parsed_from_the_ticket():
    assert [item["id"] for item in ticket_context.acceptance_criteria(OCX_79)] == ["AC1", "AC2", "AC3"]
    assert ticket_context.acceptance_criteria(OCX_79)[2]["text"] == "the savings are rounded to 2 decimal places."
    bullets = "Intro\n\n## Acceptance criteria\n- Exactly 10 items get 5 %\n- An empty order saves 0\n\n## Notes\n- x"
    assert [item["text"] for item in ticket_context.acceptance_criteria(bullets)] == [
        "Exactly 10 items get 5 %", "An empty order saves 0"]
    gherkin = "Given 10 items\nWhen the order is placed\nThen 5 % is off\n\nGiven no items\nThen it saves 0"
    assert [item["text"] for item in ticket_context.acceptance_criteria(gherkin)] == [
        "Given 10 items When the order is placed Then 5 % is off", "Given no items Then it saves 0"]
    assert ticket_context.acceptance_criteria("Just a description.") == []


def test_every_parsed_criterion_gets_a_row_also_without_the_reviewers_answer():
    criteria = ticket_context.acceptance_criteria(OCX_79)
    rows = ticket_context.acceptance_rows(criteria, [
        {"criterion": "AC2 empty order", "status": "covered", "evidence": "pay/savings.py:13"},
        {"criterion": "The savings are rounded to 2 decimal places", "status": "missing", "evidence": "no rounding"}])
    assert [(row["criterion"][:3], row["status"]) for row in rows] == [
        ("AC1", "not_assessed"), ("AC2", "covered"), ("AC3", "missing")]
    post = build_post({"verdict": "pass", "summary": "", "findings": [], "acceptance": rows}, {}, provider="github",
                      facts={"sha": "a" * 40})
    assert "| AC1: bulk_savings returns subtotal minus bulk_total. | ❔ not assessed | the review gave no answer" in (
        post.summary)
