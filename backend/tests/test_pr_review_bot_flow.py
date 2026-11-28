"""PR review bot, end to end on a real git origin with the governed tools scripted (stage A/B)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from sqlalchemy import select

from app.models import WorkflowRun
from app.services.pr_review_bot import sync as bot_sync
from app.services.pr_review_bot import webhook as bot_webhook
from app.services.pr_review_bot.events import pull_request_event
from app.services.pr_review_bot.settings import BotSettings, store_settings
from app.services.pr_review_bot.starter import TRIGGER_WEBHOOK, start_review
from app.services.workflow_runs.review.runner import run_due_reviews
from tests.pr_review_bot_flow_support import (  # noqa: F401
    FIXTURES,
    HEADERS,
    REVIEW,
    _git,
    _no_background,
    _origin,
    _payload,
    _tools,
    _workspace,
)
from tests.scripted_pool_support import scripted_pool  # noqa: F401 - fixture
from tests.workflow_run_review_support import ScriptedReviewer

pytestmark = pytest.mark.usefixtures("scripted_pool")


async def test_a_pushed_pull_request_is_checked_out_reviewed_and_answered_inline(db, monkeypatch, tmp_path):
    clone, head = _origin(tmp_path)
    tools = _tools(monkeypatch, clone)
    project_id, _record, hook = await _workspace(db)
    spawned = []
    monkeypatch.setattr(bot_webhook, "_spawn", lambda coroutine: spawned.append(coroutine) or coroutine.close())
    answer = await bot_webhook.on_scm_webhook(db, hook, _payload(head), HEADERS, is_test=False)
    assert answer == {"outcome": "queued"} and len(spawned) == 1

    event = pull_request_event(_payload(head), HEADERS)
    started = await start_review(db, project_id, event, trigger=TRIGGER_WEBHOOK)
    run = await db.get(WorkflowRun, started.run_id)
    assert (run.workflow_key, run.repository, run.branch, run.waiting_kind) == (
        "pr-review-bot", "github:acme/pay", "feature/PAY-1-totals", "awaiting_review")
    assert run.context["pr_review"]["reviewed_sha"] == head and run.pull_request["id"] == "42"
    from sqlalchemy import select

    from app.models.runtime.workflow_run import WorkflowRunEvent

    started_detail = (await db.execute(select(WorkflowRunEvent.detail).where(
        WorkflowRunEvent.run_id == run.id, WorkflowRunEvent.kind == "run_started"))).scalar_one()
    assert started_detail["trigger"] == "webhook"
    from app.services.workflow_runs.records import main_session_id

    assert await main_session_id(db, run)
    from app.services.workflow_runs.platform.dispatch import tool_context

    prepared_in = (await tool_context(db, run, "change")).workspace_root
    assert prepared_in and Path(prepared_in).resolve() != Path.cwd().resolve()
    prepare = next(call[1] for call in tools.calls if call[0] == "prepare_github_repository")
    assert prepare["review_only"] is True
    pending = [call[1] for call in tools.calls if call[0] == "post_github_pull_request_review"]
    assert pending == [{"repository": "acme/pay", "pr_number": "42", "commit": head, "commit_status": {
        "state": "pending", "description": "Octryx is reviewing", "context": "octryx/review",
        "target_url": "https://github.com/acme/pay/pull/42"}}]

    reviewer = ScriptedReviewer(REVIEW)
    assert await run_due_reviews(db, model_factory=reviewer.factory) == 1
    system, task = reviewer.tasks[0]
    assert '"suggestion"' in system and '"walkthrough"' in system
    assert "-    return int(subtotal)\n+    return round(subtotal)" in task
    await db.refresh(run)
    assert (run.status, run.outcome) == ("completed", "done")
    posted = [call[1] for call in tools.calls if call[0] == "post_github_pull_request_review"][-1]
    assert posted["commit_status"]["state"] == "failure" and posted["marker"] in posted["summary"]
    assert posted["comments"] == [{"path": "totals.py", "line": 3, "line_type": "ADDED", "body": (
        "**🔴 High** · F1\n\nUse half-away-from-zero rounding.\n\n```suggestion\n    return int(subtotal + 0.5)\n```")}]
    assert "`rates.py:9` | Rates must round the same way." in posted["summary"]
    assert "| `totals.py` | Rounds instead of truncating. | +1 −1 |" in posted["summary"]
    assert run.context["pr_review"]["posted"]["inline"] == 1

    again = await bot_webhook.on_scm_webhook(db, hook, _payload(head), HEADERS, is_test=False)
    assert again == {"outcome": "already_reviewed", "run_id": run.id} and len(spawned) == 1


async def test_a_repository_without_the_bot_a_draft_and_a_fork_start_nothing(db, monkeypatch):
    project_id, record, hook = await _workspace(db, trigger="sync")
    head = "c0ffee00c0ffee00c0ffee00c0ffee00c0ffee00"
    assert await bot_webhook.on_scm_webhook(db, hook, _payload(head), HEADERS, is_test=False) == {
        "outcome": "skipped", "reason": "bot_off"}
    store_settings(record, BotSettings("webhook"))
    await db.flush()
    assert (await bot_webhook.on_scm_webhook(db, hook, _payload(head, draft=True), HEADERS, is_test=False))[
        "reason"] == "draft"
    fork = _payload(head)
    fork["pull_request"]["head"]["repo"]["full_name"] = "outsider/pay"
    assert (await bot_webhook.on_scm_webhook(db, hook, fork, HEADERS, is_test=False))["reason"] == "fork"
    assert (await bot_webhook.on_scm_webhook(db, hook, _payload(head), HEADERS, is_test=True))["reason"] == "test_call"
    runs = (await db.execute(select(WorkflowRun).where(WorkflowRun.project_id == project_id))).scalars().all()
    assert runs == []


async def test_the_hourly_sync_starts_only_the_heads_no_run_reviewed(db, monkeypatch):
    project_id, record, _hook = await _workspace(db, trigger="both")
    page = json.loads((FIXTURES / "github_pulls_page.json").read_text())
    from app.tools.connectors.github_pr_review import _head

    async def listed(tool, arguments, context):
        assert (tool, context.project_ids) == ("list_github_pull_request_heads", [project_id])
        assert set(arguments) <= {"repository", "comments_since"} and arguments["repository"] == "acme/pay"
        return {"pull_requests": [_head(pr) for pr in page]}

    monkeypatch.setattr("app.tools.registry.execute_tool_with_plugins", listed)
    started = []

    async def start(db_, *, user, workflow_key, project_id, repository, branch, session, context, automatic):
        assert session.user_id == user.id and session.project_id == project_id
        run = WorkflowRun(project_id=project_id, workflow_kind="phased", workflow_key=workflow_key, title="bot",
                          requested_by=user.id, repository=repository, branch=branch, context=context)
        db_.add(run)
        await db_.flush()
        started.append((branch, user.username, automatic))
        return run

    assert await bot_sync.sync_repository(db, record, start=start) == {"started": 1, "skipped": 2}
    assert started == [("feature/PAY-1-totals", f"review-bot-{project_id}", True)]
    assert await bot_sync.sync_repository(db, record, start=start) == {"already_reviewed": 1, "skipped": 2}


async def test_a_failed_checkout_leaves_an_error_status_and_blocks_the_run(db, monkeypatch, tmp_path):
    tools = _tools(monkeypatch, tmp_path, prepare_github_repository=[{"error": "repository not found",
                                                                      "status_code": 404}])
    project_id, _record, _hook = await _workspace(db)
    head = "c0ffee00c0ffee00c0ffee00c0ffee00c0ffee00"
    started = await start_review(db, project_id, pull_request_event(_payload(head), HEADERS), trigger="webhook")
    run = await db.get(WorkflowRun, started.run_id)
    assert (run.status, run.outcome) == ("completed", "blocked")
    status = [call[1]["commit_status"] for call in tools.calls if call[0] == "post_github_pull_request_review"]
    assert status[0]["state"] == "error" and "repository not found" in status[0]["description"]
    assert run.context["pr_review"]["failure"] == {"reason": "repository not found", "status_posted": True}


async def test_an_error_status_that_cannot_be_posted_fails_the_report_and_says_why(db, monkeypatch, tmp_path):
    _tools(monkeypatch, tmp_path, prepare_github_repository=[{"error": "operation 'branch' is denied"}],
           post_github_pull_request_review=[{"error": "Circuit breaker is open for github@platform"}])
    project_id, _record, _hook = await _workspace(db)
    started = await start_review(db, project_id, pull_request_event(_payload("c0ffee00" * 5), HEADERS),
                                 trigger="webhook")
    run = await db.get(WorkflowRun, started.run_id)
    assert (run.status, run.outcome) == ("completed", "blocked")
    assert run.context["pr_review"]["failure"] == {
        "reason": "operation 'branch' is denied", "status_posted": False,
        "post_error": "Circuit breaker is open for github@platform"}
    assert run.context["actions"]["report_failure"]["result"] == "failed"
    from app.services.pr_review_bot.starter import reviewed_run

    assert await reviewed_run(db, project_id, pull_request_event(_payload("c0ffee00" * 5), HEADERS)) is None


async def test_pr4_a_signature_change_that_breaks_a_call_outside_the_diff_fails_even_when_the_reviewer_passes(
        db, monkeypatch, tmp_path):
    origin = tmp_path / "origin"
    (origin / "pay").mkdir(parents=True)
    _git(origin, "init", "-q", "-b", "main")
    (origin / "pay/__init__.py").write_text("")
    (origin / "pay/totals.py").write_text("def vat(amount):\n    return amount * 0.081\n")
    (origin / "pay/report.py").write_text("from .totals import vat\n\n\ndef summary(net):\n    return vat(net)\n")
    _git(origin, "add", "-A")
    _git(origin, "commit", "-qm", "init")
    _git(origin, "checkout", "-q", "-b", "feature/PAY-1-totals")
    (origin / "pay/totals.py").write_text("def vat(amount, rate):\n    return amount * rate\n")
    _git(origin, "commit", "-qam", "VAT takes its rate")
    head = _git(origin, "rev-parse", "HEAD")
    _git(origin, "checkout", "-q", "main")
    _git(tmp_path, "clone", "-q", str(origin), str(tmp_path / "pay"))
    tools = _tools(monkeypatch, tmp_path / "pay")
    project_id, _record, _hook = await _workspace(db)
    started = await start_review(db, project_id, pull_request_event(_payload(head), HEADERS), trigger="webhook")
    reviewer = ScriptedReviewer({"verdict": "pass", "summary": "Looks good.", "findings": []})
    assert await run_due_reviews(db, model_factory=reviewer.factory) == 1
    assert "pay/report.py:5: return vat(net)" not in reviewer.tasks[0][1]
    assert "pay/totals.py: vat(amount) -> vat(amount, rate)" in reviewer.tasks[0][1]
    assert "Calls outside the diff this change breaks" in reviewer.tasks[0][1]
    assert "pay/report.py:5: `vat(amount)` became `vat(amount, rate)`" in reviewer.tasks[0][1]
    run = await db.get(WorkflowRun, started.run_id)
    await db.refresh(run)
    posted = [call[1] for call in tools.calls if call[0] == "post_github_pull_request_review"][-1]
    assert posted["commit_status"]["state"] == "failure"
    assert "## Octryx review: changes requested" in posted["summary"]
    assert "**Blocking (deterministic):** 1 call(s) outside the diff" in posted["summary"]
    assert "> Reviewer: Looks good." in posted["summary"]
    assert "`pay/report.py:5`" in posted["summary"] and "misses the required argument 'rate'" in posted["summary"]
