"""What one review covers: the test contract a person confirmed, and a change too large for one call split into parts below the price tier."""

from __future__ import annotations

import pytest

from app.models import WorkflowRun
from app.services.workflow_runs.records import new_chat_session
from app.services.workflow_runs.review.model import ReviewAnswer
from app.services.workflow_runs.review.runner import run_due_reviews
from tests.phased_workflow_fixtures import admin_user
from tests.scripted_pool_support import scripted_pool  # noqa: F401 - fixture
from tests.test_workflow_run_pause import _turn
from tests.workflow_run_review_support import CHANGES, PASS, ScriptedReviewer, _started

pytestmark = pytest.mark.usefixtures("scripted_pool")


def _contract(*criteria):
    return {"subject": "test_contract", "version": 3, "change_plan_id": "plan-1", "acceptance_criteria": [
        {"id": key, "text": text, "tests": [test], "test_roles": {test: "new"}} for key, text, test in criteria]}


class PartsReviewer(ScriptedReviewer):
    async def answer(self, *, system: str, user: str) -> ReviewAnswer:
        parted = "Do not give a verdict now" in system
        self.answers = [{"notes": [{"file": "big.py", "line": 3, "severity": "low", "problem": "naming"}],
                         "covers": "values"} if parted else PASS]
        return await super().answer(system=system, user=user)


@pytest.mark.asyncio
async def test_a_change_larger_than_a_review_takes_gets_no_verdict_on_a_part_of_it(db, tmp_path):
    run, session = await _started(db, tmp_path)
    # Harmless changes first, the rest past the reviewer's limit: before the fix the reviewer saw only the start.
    from app.services.workflow_runs.review.evidence import MAX_DIFF

    (tmp_path / "w" / "aaa_bulk.py").write_text("x = 1\n" * (MAX_DIFF // 6 + 500))
    (tmp_path / "w" / "zzz_hidden.py").write_text("import os\nos.system('evil')\n")
    await _turn(db, session.id, ["knowledge_search"])
    reviewer = ScriptedReviewer(PASS)
    assert await run_due_reviews(db, model_factory=reviewer.factory) == 1
    await db.refresh(run)
    assert (run.status, run.pause_reason) == ("paused", "review_no_decision") and reviewer.tasks == []
    assert "larger than a review takes" in run.node_state["pause"]["message"]


@pytest.mark.asyncio
async def test_the_reviewer_judges_against_the_test_contract_a_person_confirmed_and_never_a_draft(db, tmp_path):
    from datetime import timedelta

    from app.services.workflow_runs.pause import record_decision
    from app.services.workflow_runs.review.verdict import SEVERITY_RULE
    from app.time_utils import utc_now

    run, session = await _started(db, tmp_path)
    confirmed = _contract(("AC3", "max_words of 0 returns an empty string.", "t.py::test_zero"),
                          ("AC4", "A negative max_words raises ValueError.", "t.py::test_negative"))
    record_decision(db, run, kind="confirmation", subject="test_contract", action="confirmed", payload=confirmed,
                    user_id=None).created_at = utc_now() - timedelta(minutes=2)
    # A draft of the same tests that nobody confirmed is no fact for the reviewer.
    draft = _contract(("AC3", "max_words of 0 raises ValueError.", "t.py::test_zero"))
    run.context = {**dict(run.context or {}), "outputs": {"test_contract": {"record": {"criteria": draft[
        "acceptance_criteria"]}}}, "confirmed_tests": ["t.py::test_zero", "t.py::test_negative"]}
    await db.commit()
    await _turn(db, session.id, ["knowledge_search"])
    reviewer = ScriptedReviewer(CHANGES)
    await run_due_reviews(db, model_factory=reviewer.factory)
    system, task = reviewer.tasks[0]
    fence = task.split("Review fence for this review: ", 1)[1].split(".", 1)[0]
    facts = task.split(f"<<<test facts {fence}>>>", 1)[1].split(f"<<<end test facts {fence}>>>", 1)[0]
    assert "contradicts a confirmed criterion" in system and "a helper it uses" in system
    assert 'a rewrite with the same behaviour, reusing another helper' in system and SEVERITY_RULE in system
    assert "Do not recompute values the tests compute" in system
    assert "Confirmed test contract (version 3, plan plan-1" in facts
    assert "- AC3: max_words of 0 returns an empty string. (tests: t.py::test_zero (new))" in facts
    assert "- AC4: A negative max_words raises ValueError. (tests: t.py::test_negative (new))" in facts
    assert "0 raises ValueError" not in task
    # The reviewer's real findings still count: nothing is filtered, the run goes back to the fix phase.
    run = await db.get(WorkflowRun, run.id)
    await db.refresh(run)
    assert (run.current_node_id, run.gate_results["gate"]["state"]) == ("work", "failed")

    # A contract changed after the confirm is no confirmed contract any more.
    from app.services.workflow_runs.review.evidence import confirmed_contract

    record_decision(db, run, kind="confirmation", subject="test_contract", action="changed", payload=draft,
                    user_id=None).created_at = utc_now()
    await db.flush()
    assert await confirmed_contract(db, run) == ""


def test_a_change_too_large_for_one_call_is_split_into_parts_that_hold_all_of_it():
    from app.services.workflow_runs.review.reading import change_parts

    diff = "".join(f"diff --git a/f{n}.py b/f{n}.py\n" + "+x = 1\n" * 40 for n in range(5))
    diff += "diff --git a/big.py b/big.py\n" + "+y = 2\n" * 400
    parts = change_parts(diff, 1_000)
    assert "".join(parts) == diff and all(len(part) <= 1_000 for part in parts) and len(parts) > 3


@pytest.mark.asyncio
async def test_every_reviewer_call_of_a_large_change_stays_below_the_price_tier(db, tmp_path, monkeypatch):
    from app.services.workflow_runs.review import reading

    # A small budget (the frame of a run in its Workspace still fits), so the test change is "large".
    monkeypatch.setattr(reading, "CALL_TOKENS", 5_000)
    monkeypatch.setattr(reading, "MIN_PART_CHARS", 1_000)
    run, session = await _started(db, tmp_path)
    (tmp_path / "w" / "big.py").write_text("".join(f"value_{n} = {n}\n" for n in range(1_500)))
    await _turn(db, session.id, ["knowledge_search"])
    reviewer = PartsReviewer()
    assert await run_due_reviews(db, model_factory=reviewer.factory) == 1
    await db.refresh(run)
    assert run.context["review"]["verdict"] == "pass"
    part_calls = [task for task in reviewer.tasks if "Do not give a verdict now" in task[0]]
    assert len(part_calls) > 1
    budget = reading.CALL_TOKENS * reading.CHARS_PER_TOKEN
    assert all(len(system) + len(user) <= budget for system, user in part_calls)
    assert all(f"value_{n} = {n}" in "".join(user for _system, user in part_calls) for n in (0, 750, 1_499))
    verdict_system, verdict_user = reviewer.tasks[-1]
    assert len(verdict_system) + len(verdict_user) <= budget
    assert "value_1499" not in verdict_user and "read in" in verdict_user and "naming" in verdict_user


@pytest.mark.asyncio
async def test_a_review_call_above_the_haiku_price_tier_is_priced_at_the_step(db, monkeypatch):
    from decimal import Decimal
    from types import SimpleNamespace

    from app.services.workflow_runs.review import attempts
    from app.services.workflow_runs.review.model import call_usage, summed_usage

    below = call_usage("claude-haiku-5-5", "p", "", 90_000, 1_000)
    above = call_usage("claude-haiku-5-5", "p", "", 151_000, 2_000)
    flat = call_usage("claude-sonnet-5-5", "p", "", 151_000, 2_000)
    assert (below.over_tier_in, above.over_tier_in, flat.over_tier_in) == (0, 151_000, 0)
    both = summed_usage(below, above)
    assert (both.tokens_in, both.over_tier_in, both.tier_factor) == (241_000, 151_000, 5)

    async def attribution(db, *, provider, model, tokens_in, tokens_out, driver=None):
        return SimpleNamespace(cost=Decimal(tokens_in) / Decimal(1_000_000), cost_source="", status="catalog")

    admin = await admin_user(db)
    session = await new_chat_session(db, admin, None)

    async def main_session(_db, _run):
        return session.id

    monkeypatch.setattr("app.services.budget.compute_usage_event_cost_attribution", attribution)
    monkeypatch.setattr("app.services.workflow_runs.records.main_session_id", main_session)
    added = []
    await attempts._record_usage(SimpleNamespace(add=added.append), SimpleNamespace(requested_by=admin.id), both, "a1")
    assert added[0].cost == Decimal("0.241") + Decimal("0.151") * 4
