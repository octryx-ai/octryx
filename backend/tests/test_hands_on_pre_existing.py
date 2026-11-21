"""A regression scenario red on the run's base commit too is reported, never blocking (otherwise a scenario that
fails on another open bug needs an admin to waive it by hand)."""

from __future__ import annotations

import pytest

from app.services.workflow_runs.hands_on import step
from tests.hands_on_support import _answer, _at_hands_on, _Model


@pytest.mark.asyncio
async def test_a_regression_red_on_the_base_too_is_reported_never_blocking(db, monkeypatch):
    run, session, _offered, factory = await _at_hands_on(db, monkeypatch, model=_Model(_answer()))
    run.context = {**dict(run.context or {}), "base_sha": "64f7dac5d56c88b4cc57b529fdb8655a044ac27c"}
    await step.generate_due(db, model_factory=factory)
    run = await db.get(type(run), run.id)
    view = step.contract_view(run)
    assert view["base_sha"].startswith("64f7dac5")

    def report(feature_pre_existing: bool) -> dict:
        return {"node_id": view["node_id"], "entry": view["entry"], "state": "ran", "scenarios": [
            {"id": "S1", "passed": not feature_pre_existing, "failed_step": 2,
             **({"pre_existing": view["base_sha"]} if feature_pre_existing else {})},
            {"id": "S2", "passed": False, "failed_step": 2, "pre_existing": view["base_sha"]},
            {"id": "S3", "passed": True}, {"id": "S4", "passed": True}]}

    assert await step.record_report(db, run, report(False), session_id=session.id) == "green"
    (kept,) = [item for item in step.run_view(run)["results"] if item.get("pre_existing")]
    assert kept["id"] == "S2" and "also red on the base 64f7dac5d56c" in kept["pre_existing"]
    assert kept["failed_step"].startswith("3:")  # what failed stays visible


@pytest.mark.asyncio
async def test_a_feature_scenario_marked_pre_existing_stays_red(db, monkeypatch):
    run, session, _offered, factory = await _at_hands_on(db, monkeypatch, model=_Model(_answer()))
    await step.generate_due(db, model_factory=factory)
    run = await db.get(type(run), run.id)
    view = step.contract_view(run)
    report = {"node_id": view["node_id"], "entry": view["entry"], "state": "ran", "scenarios": [
        {"id": "S1", "passed": False, "failed_step": 2, "pre_existing": "abc"},
        {"id": "S2", "passed": True}, {"id": "S3", "passed": True}, {"id": "S4", "passed": True}]}
    assert await step.record_report(db, run, report, session_id=session.id) == "red"
