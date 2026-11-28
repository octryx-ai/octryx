"""Claude Code compacts a long run session itself: the offer carries the class's context cap as the window, a session
past the cap keeps going instead of restarting with a handoff note, and each compaction is a ``session_compacted``."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.models import WorkflowRunEvent
from app.services.devices.job_offer import offer_body
from app.services.workflow_runs.octryx import compaction
from tests.scripted_pool_support import scripted_pool  # noqa: F401 - fixture

pytestmark = pytest.mark.usefixtures("scripted_pool")


def _run(cap):
    return SimpleNamespace(context={"size_class": {"class": "S", "classes": {"S": {"context_cap_tokens": cap}}}})


def test_the_offer_carries_the_class_cap_as_the_window():
    assert compaction.window(_run(200_000)) == 200_000
    assert compaction.window(_run(50_000)) == 100_000  # Claude Code's own minimum
    assert compaction.window(_run(None)) is None and compaction.window(None) is None
    job = SimpleNamespace(id="j", turn_id="t", turn_prompt="p", folder="/f", profile="seat", turn_model="",
                          workspace_id="w", session_id="s", policy_decision_id=None, claude_session_id=None,
                          resume_claude_session_id=None)
    assert offer_body(job, limits={}, compact_window=200_000)["compact_window"] == 200_000
    assert "compact_window" not in offer_body(job, limits={})


@pytest.mark.asyncio
async def test_only_an_engine_without_auto_compaction_starts_fresh_past_the_cap(db, monkeypatch):
    from app.services.devices import job_engine

    engines = {"cs-claude": "claude_code", "th-codex": "codex"}

    async def engine_of(_db, session_id, **_):
        return engines.get(session_id)

    monkeypatch.setattr(job_engine, "_engine_of_session", engine_of)
    assert await compaction.compacts_itself(db, "cs-claude") is True
    assert await compaction.compacts_itself(db, "unknown") is True  # a session no job knows is Claude Code's
    assert await compaction.compacts_itself(db, "th-codex") is False
    assert await compaction.compacts_itself(db, "") is False


@pytest.mark.asyncio
async def test_a_compaction_is_the_runs_event_with_its_trigger(db):
    from app.services.workflow_runs.records import start_run
    from tests.phased_workflow_fixtures import admin_user, publish_phased, run_workspace
    from tests.test_workflow_size_class_merge import _definition

    workspace_id = await run_workspace(db, await admin_user(db))
    run = await start_run(db, user=await admin_user(db), workflow_key=await publish_phased(db, _definition({})),
                          project_id=workspace_id)
    assert await compaction.record(db, run, "s-1", {"stage": "post", "trigger": "auto", "summary_chars": 812}) == {
        "state": "recorded"}
    assert (await compaction.record(db, run, "s-1", {"stage": "later"}))["state"] == "refused"
    await db.flush()
    event = (await db.execute(select(WorkflowRunEvent).where(
        WorkflowRunEvent.run_id == run.id, WorkflowRunEvent.kind == compaction.EVENT))).scalar_one()
    assert event.detail == {"stage": "post", "trigger": "auto", "session_id": "s-1", "context_tokens": 0,
                            "summary_chars": 812}
