"""PR review bot, the instant trigger: a pull request Octryx opened, or a commit Octryx pushed onto one,
is reviewed at once, without a webhook and without waiting for the hourly sync."""

from __future__ import annotations

import json

from sqlalchemy import select

from app.models import WorkflowRun
from app.models.runtime.workflow_run import WorkflowRunEvent
from app.services.pr_review_bot import instant
from app.services.pr_review_bot.settings import BotSettings, store_settings
from app.tools.connectors.github_pr_review import _head
from tests.pr_review_bot_flow_support import FIXTURES, _workspace


def _authoring_run(project_id: str, **changes) -> WorkflowRun:
    values = {"project_id": project_id, "workflow_kind": "phased", "workflow_key": "story-delivery", "title": "s",
              "requested_by": "u", "repository": "github:acme/pay", "branch": "feature/PAY-1-totals",
              "context": {"head_sha": "a" * 40}, "pull_request": {"id": "42", "state": "open"}}
    return WorkflowRun(**{**values, **changes})


def _listing(monkeypatch, numbers=(42,)) -> list[str]:
    page = [pr for pr in json.loads((FIXTURES / "github_pulls_page.json").read_text()) if pr["number"] in numbers]
    calls = []

    async def listed(tool, arguments, context):
        calls.append(tool)
        assert arguments == {"repository": "acme/pay"}  # heads only: the comment poll keeps its own cursor
        return {"pull_requests": [_head(pr) for pr in page]}

    monkeypatch.setattr("app.tools.registry.execute_tool_with_plugins", listed)
    return calls


def _starts(monkeypatch) -> list[tuple[str, str]]:
    started = []

    async def start(db_, *, user, workflow_key, project_id, repository, branch, session, context, automatic):
        run = WorkflowRun(project_id=project_id, workflow_kind="phased", workflow_key=workflow_key, title="bot",
                          requested_by=user.id, repository=repository, branch=branch, context=context)
        db_.add(run)
        await db_.flush()
        started.append((branch, context["pr_review"]["trigger"]))
        return run

    monkeypatch.setattr("app.services.workflow_runs.records.start_run", start)
    return started


async def _events(db) -> list[WorkflowRunEvent]:
    return list((await db.execute(select(WorkflowRunEvent).where(
        WorkflowRunEvent.kind == instant.EVENT_KIND))).scalars())


async def test_only_an_open_pull_request_of_an_octryx_run_records_a_new_head(db):
    project_id, _record, _hook = await _workspace(db)
    runs = [_authoring_run(project_id), _authoring_run(project_id, pull_request={}),
            _authoring_run(project_id, pull_request={"id": "42", "state": "merged"}),
            _authoring_run(project_id, workflow_key="pr-review-bot")]
    db.add_all(runs)
    await db.flush()
    for run in runs:
        instant.head_ready(db, run)
    await db.flush()
    assert [(event.run_id, event.detail) for event in await _events(db)] == [
        (runs[0].id, {"pr_id": "42", "head_sha": "a" * 40})]


async def test_a_new_head_is_reviewed_at_the_next_tick_once(db, monkeypatch):
    project_id, _record, _hook = await _workspace(db, trigger="sync")
    calls, started = _listing(monkeypatch), _starts(monkeypatch)
    run = _authoring_run(project_id)
    db.add(run)
    await db.flush()
    instant.head_ready(db, run)
    instant.head_ready(db, run)
    await db.commit()
    cursor = instant.Cursor()
    assert await instant.start_due(db, cursor) == {"started": 1}
    assert started == [("feature/PAY-1-totals", "octryx_pr")] and calls == ["list_github_pull_request_heads"]
    assert await instant.start_due(db, cursor) == {}
    assert len(calls) == 1
    instant.head_ready(db, run)
    await db.commit()
    assert await instant.start_due(db, cursor) == {"already_reviewed": 1} and len(started) == 1


async def test_a_closed_pull_request_or_a_repository_without_the_bot_starts_nothing(db, monkeypatch):
    project_id, record, _hook = await _workspace(db, trigger="webhook")
    calls, started = _listing(monkeypatch, numbers=()), _starts(monkeypatch)
    run = _authoring_run(project_id)
    db.add(run)
    await db.flush()
    instant.head_ready(db, run)
    await db.commit()
    assert await instant.start_due(db, instant.Cursor()) == {"not_open": 1} and started == []
    store_settings(record, BotSettings("off"))
    await db.commit()
    assert await instant.start_due(db, instant.Cursor()) == {"skipped": 1} and len(calls) == 1


async def test_a_failing_listing_is_tried_again_then_given_up(db, monkeypatch):
    project_id, _record, _hook = await _workspace(db)

    async def broken(tool, arguments, context):
        raise RuntimeError("provider down")

    monkeypatch.setattr("app.tools.registry.execute_tool_with_plugins", broken)
    run = _authoring_run(project_id)
    db.add(run)
    await db.flush()
    instant.head_ready(db, run)
    await db.commit()
    cursor = instant.Cursor()
    assert [await instant.start_due(db, cursor) for _ in range(instant.ATTEMPTS)] == [{}, {}, {"failed": 1}]
    assert await instant.start_due(db, cursor) == {}
