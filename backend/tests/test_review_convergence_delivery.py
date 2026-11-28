"""In a delivery, follow-up review rounds converge, only an open high finding after the revisions holds a story or asks the product owner, and the reviewer sees only this change's screenshots."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.phased_workflow_fixtures import admin_user
from tests.review_convergence_support import PNG, _delivery, _finding, _started
from tests.scripted_pool_support import scripted_pool  # noqa: F401 - fixture

pytestmark = pytest.mark.usefixtures("scripted_pool")


@pytest.mark.asyncio
async def test_a_follow_up_round_answers_the_previous_ids_and_converges(db, tmp_path):
    from app.services.workflow_runs.review.convergence import FOLLOW_UP_RULE
    from app.services.workflow_runs.review.runner import run_due_reviews
    from app.services.workflow_runs.review.verdict import ANSWER_CONTRACT
    from tests.test_workflow_run_pause import _turn
    from tests.workflow_run_review_support import ScriptedReviewer

    run, session = await _started(db, tmp_path, _delivery(tmp_path, {"tasks": False}))
    first = {"verdict": "changes", "summary": "two", "findings": [
        _finding("medium", "totals.py", "round the total down"), _finding("high", "totals.py", "keep cents")]}
    follow = {"summary": "one left", "previous": [{"id": "F1", "status": "fixed"}, {"id": "F2", "status": "not_fixed"}],
              "findings": [_finding("medium", "totals.py", "a new nit")]}
    done = {"summary": "all fixed", "previous": [{"id": "F2", "status": "fixed"}], "findings": []}
    reviewer = ScriptedReviewer(first, follow, done)
    for _ in range(3):
        await _turn(db, session.id, ["knowledge_search"])
        assert await run_due_reviews(db, model_factory=reviewer.factory) == 1
        await db.refresh(run)
        if run.status == "completed":
            break
        review = run.context["review"]
        if len(reviewer.tasks) == 2:
            assert [(item["id"], item["fix"]) for item in review["findings"]] == [("F2", "keep cents")]
            assert {item["fix"] for item in review["dropped"]} == {"round the total down", "a new nit"}
    (system1, _), (system2, task2) = reviewer.tasks[:2]
    assert ANSWER_CONTRACT in system1 and FOLLOW_UP_RULE not in system1
    assert FOLLOW_UP_RULE in system2 and ANSWER_CONTRACT not in system2
    assert '"id": "F1"' in task2 and '"id": "F2"' in task2
    assert run.status == "completed" and run.context["review"]["verdict"] == "pass"


@pytest.mark.asyncio
@pytest.mark.parametrize("severity, accepted", [("medium", True), ("high", False)])
async def test_after_the_revisions_only_a_high_finding_asks_the_product_owner(db, tmp_path, severity, accepted):
    from sqlalchemy import select

    from app.models import WorkflowRunDecision
    from app.services.workflow_runs.review.runner import run_due_reviews
    from tests.test_workflow_run_pause import _turn
    from tests.workflow_run_review_support import ScriptedReviewer

    run, session = await _started(db, tmp_path, _delivery(tmp_path, {"tasks": False}))
    changes = {"verdict": "changes", "summary": "No.", "findings": [_finding(severity, "totals.py", "round down")]}
    still = {"summary": "No.", "previous": [{"id": "F1", "status": "not_fixed"}], "findings": []}
    reviewer = ScriptedReviewer(changes, still, still)
    for _ in range(3):
        await _turn(db, session.id, ["knowledge_search"])
        assert await run_due_reviews(db, model_factory=reviewer.factory) == 1
        await db.refresh(run)
    assert (run.status == "completed") is accepted
    if not accepted:
        assert run.node_state["waiting"]["subject"] == "decisions"
        return
    assert [item["fix"] for item in run.context["review_notes"]] == ["round down"]
    decision = (await db.execute(select(WorkflowRunDecision).where(
        WorkflowRunDecision.run_id == run.id, WorkflowRunDecision.action == "confirmed"))).scalars().all()[-1]
    assert decision.payload["review_notes"][0]["fix"] == "round down"
    assert "no high finding after 2 automatic revisions" in decision.payload["auto_accepted"]


@pytest.mark.asyncio
async def test_a_medium_finding_does_not_hold_back_a_done_task(db, tmp_path):
    from app.services.workflow_runs.review.runner import run_due_reviews
    from tests.test_workflow_run_pause import _turn
    from tests.workflow_run_review_support import ScriptedReviewer

    run, session = await _started(db, tmp_path, _delivery(tmp_path, {"auto_revise": 0}))
    await _turn(db, session.id, ["knowledge_search"])
    run.context = {**dict(run.context or {}), "task_list": [
        {"id": "T1", "text": "total", "proof": "t.py::test_total", "status": "done"}]}
    await db.commit()
    reviewer = ScriptedReviewer({"verdict": "changes", "summary": "nit", "findings": [
        _finding("medium", "totals.py", "T1: spacing in the total")]})
    assert await run_due_reviews(db, model_factory=reviewer.factory) == 1
    await db.refresh(run)
    assert run.context["task_list"][0]["status"] == "verified"
    assert run.status == "completed" and run.context["review_notes"][0]["fix"] == "T1: spacing in the total"


@pytest.mark.asyncio
async def test_the_reviewer_sees_only_this_changes_screenshots_and_the_capture_rule(db, tmp_path):
    from app.services.workflow_runs.review.reading import SCREENS_RULE
    from app.services.workflow_runs.review.runner import run_due_reviews
    from tests.test_workflow_run_pause import _turn

    run, session = await _started(db, tmp_path, _delivery(tmp_path, {"tasks": False}, {"screens": True}), {
        "packmate/e2e/members.spec.ts": "shot('members-page.png')", ".gitignore": "test-reports/\n"})
    root = Path(session.metadata_["workspace_root"])
    folder = root / "test-reports" / "screenshots"
    folder.mkdir(parents=True)
    for name in ("members-page.png", "totals.png"):
        (folder / name).write_bytes(PNG)
    await _turn(db, session.id, ["knowledge_search"])
    run.context = {**dict(run.context or {}), "local_path": str(root)}
    await db.commit()
    seen = []

    class Reviewer:
        async def factory(self, db, *, project_id, reviewer=None):
            return self

        async def answer(self, *, system, user, images=None):
            from app.services.workflow_runs.review.model import ReviewAnswer, ReviewUsage

            seen.append((system, [image.name for image in images or []]))
            answer = ({"audit": []} if images else {"verdict": "pass", "summary": "ok", "findings": []})
            return ReviewAnswer(answer, ReviewUsage(model="m", tokens_in=1, tokens_out=1))

    assert await run_due_reviews(db, model_factory=Reviewer().factory) == 1
    assert seen[0][1] == ["totals.png"]
    # The review result names the screenshot it judged, pinned by its hash.
    import hashlib

    await db.refresh(run)
    assert run.context["review"]["screens"] == [{"name": "totals.png", "media_type": "image/png", "size": len(PNG),
                                                 "sha256": hashlib.sha256(PNG).hexdigest()}]
    assert "fixed bar" in SCREENS_RULE and SCREENS_RULE in seen[0][0]
    assert "Never read colours or contrast ratios off an image" in SCREENS_RULE


# --- on_open_high: a high finding left after the revisions waits or goes on to the pull request --

@pytest.mark.asyncio
@pytest.mark.parametrize("setting, continued", [("wait", False), ("continue_with_findings", True)])
async def test_an_open_high_finding_after_the_revisions_waits_or_continues_by_the_node(db, tmp_path, setting, continued):
    from sqlalchemy import select

    from app.models import WorkflowRunEvent
    from app.services.workflow_runs.review.runner import run_due_reviews
    from tests.test_workflow_run_pause import _turn
    from tests.workflow_run_review_support import ScriptedReviewer

    run, session = await _started(db, tmp_path, _delivery(tmp_path, {"tasks": False, "on_open_high": setting}))
    changes = {"verdict": "changes", "summary": "No.", "findings": [
        _finding("medium", "totals.py", "name it"), _finding("high", "totals.py", "keep cents")]}
    still = {"summary": "No.", "previous": [{"id": "F1", "status": "not_fixed"}, {"id": "F2", "status": "not_fixed"}],
             "findings": []}
    reviewer = ScriptedReviewer(changes, still, still)
    for _ in range(3):
        await _turn(db, session.id, ["knowledge_search"])
        assert await run_due_reviews(db, model_factory=reviewer.factory) == 1
        await db.refresh(run)
    events = (await db.execute(select(WorkflowRunEvent).where(WorkflowRunEvent.run_id == run.id))).scalars().all()
    accepted = [event for event in events if event.kind == "accepted_with_open_findings"]
    from app.services.workflow_runs.views import run_view

    view = await run_view(db, run, access="write", user=await admin_user(db))
    if not continued:
        assert run.node_state["waiting"]["subject"] == "decisions" and not accepted
        assert view["open_findings"] == []
        return
    assert [(item["severity"], item["fix"], item["file"]) for item in view["open_findings"]] == [
        ("high", "keep cents", "totals.py"), ("medium", "name it", "totals.py")]
    assert run.status == "completed"
    assert [item["severity"] for item in run.context["open_findings"]][0] == "high"
    assert accepted and accepted[0].detail["high"] == 1 and "still open after 2" in accepted[0].detail["reason"]


def test_on_open_high_comes_from_the_node_waits_when_unset_and_is_validated():
    from app.services.workflow_runs.auto_accept import on_open_high
    from app.services.workflow_runs.graph_validation import validate_phased_definition
    from tests.test_ticket_delivery import _definition as delivery

    assert on_open_high(SimpleNamespace(config={})) == "wait"
    assert on_open_high(SimpleNamespace(config={"on_open_high": "continue_with_findings"})) == "continue_with_findings"
    definition = delivery()
    definition["nodes"][3]["config"]["on_open_high"] = "maybe"
    assert "on_open_high" in {error["code"] for error in validate_phased_definition(definition)["errors"]}


@pytest.mark.asyncio
async def test_the_pull_request_opens_with_the_open_findings_on_top(db, monkeypatch):
    from app.services.workflow_runs.platform import scm
    from tests.linked_accounts_support import _cloud_run, _scripted
    from tests.phased_workflow_fixtures import admin_user

    run = await _cloud_run(db, await admin_user(db))
    run.context = {**dict(run.context or {}), "open_findings": [
        {"severity": "high", "file": "src/pay.py", "line": 7, "fix": "Keep the cents."},
        {"severity": "low", "fix": "Name the helper."}]}
    calls = _scripted(monkeypatch, {"id": 9, "url": "https://bitbucket.org/acme/payments/pull-requests/9",
                                    "status": "created", "reviewers_unresolved": []})
    assert (await scm.open_pr(db, run, {})).ok
    pr = dict(next(arguments for tool, arguments in calls if tool == "create_bitbucket_pull_request"))
    assert pr["description"].startswith("## Open review findings — decide before merging")
    assert pr["description"].index("- high (src/pay.py:7): Keep the cents.") < pr["description"].index("- low")


@pytest.mark.asyncio
async def test_no_high_finding_but_unverified_tasks_continues_an_unattended_story(db, tmp_path):
    from sqlalchemy import select

    from app.models import WorkflowRunEvent
    from app.services.workflow_runs.review.runner import run_due_reviews
    from tests.test_workflow_run_pause import _turn
    from tests.workflow_run_review_support import ScriptedReviewer

    run, session = await _started(db, tmp_path, _delivery(tmp_path, {"tasks": True,
                                                                       "on_open_high": "continue_with_findings"}))
    changes = {"verdict": "changes", "summary": "No.", "findings": [_finding("medium", "totals.py", "name it")]}
    still = {"summary": "No.", "previous": [{"id": "F1", "status": "not_fixed"}], "findings": []}
    reviewer = ScriptedReviewer(changes, still, still)
    for _ in range(3):
        await _turn(db, session.id, ["knowledge_search"])
        assert await run_due_reviews(db, model_factory=reviewer.factory) == 1
        await db.refresh(run)
    events = (await db.execute(select(WorkflowRunEvent).where(WorkflowRunEvent.run_id == run.id))).scalars().all()
    accepted = [event for event in events if event.kind == "accepted_with_open_findings"]
    assert run.status == "completed" and accepted and accepted[0].detail["high"] == 0
    assert "not every task verified" in accepted[0].detail["reason"]
