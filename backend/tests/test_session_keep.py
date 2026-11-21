"""The team member who made the mistake fixes it, with their context. Live 4f4139ff: after the
escalation S -> M every red green gate ended the turn and the next one started a new pass (the Claude Code session was
resumed, but each pass cost a turn change and ~6k tokens of prompt). Every size class shares the session and changes
phases inside the turn; an escalation keeps both; only another role or model starts a session of its own."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from app.services.workflow_runs.octryx.run_session import phase_change, shared_run_session, shares
from app.services.workflow_runs.seeding import SEEDS_PATH

TARGET = {"device_id": "dev_1", "folder": "/repo", "profile": "seat"}


def _classes(key: str) -> dict:
    flows = json.loads(SEEDS_PATH.read_text(encoding="utf-8"))
    return next(flow for flow in flows if flow["key"] == key)["definition"]["size_classes"]["classes"]


def _run(classes: dict, size: str, **context) -> SimpleNamespace:
    return SimpleNamespace(id="r", context={"size_class": {"class": size, "classes": classes}, **context})


@pytest.mark.parametrize("key", ["bug-fix-reproduction", "epic-delivery", "spec-writing"])
def test_every_shipped_class_shares_the_session_and_keeps_the_turn(key):
    for size, settings in _classes(key).items():
        run = _run(_classes(key), size)
        assert shares(run) and phase_change(run) == "same_turn", (key, size, settings)


def test_an_escalation_keeps_the_session_and_the_turn():
    classes = _classes("bug-fix-reproduction")
    for size in ("S", "M", "L"):  # the escalation path S -> M -> L
        assert phase_change(_run(classes, size)) == "same_turn"
    assert shares(_run({"small": {}}, "small"))  # a class that says nothing shares too
    assert not shares(_run({"big": {"session": "per_phase"}}, "big"))  # unless it says otherwise
    assert not shares(SimpleNamespace(context={}))  # no class: the workflow's own behaviour


@pytest.mark.asyncio
async def test_a_red_gate_back_into_the_phase_resumes_its_session_and_another_role_gets_its_own(monkeypatch):
    from app.services.workflow_runs.octryx import phase_sessions, run_session

    phases = {"fix": SimpleNamespace(id="fix", config={"agent": "engineer"}),
              "review": SimpleNamespace(id="review", config={"agent": "reviewer"})}

    async def graph(_db, _run):
        return SimpleNamespace(nodes=phases)

    async def here(_db, entry, _target):
        return str(entry.get("claude_session_id") or "")

    monkeypatch.setattr("app.services.workflow_runs.graph.graph_for_run", graph)
    monkeypatch.setattr(phase_sessions, "_session_here", here)
    last = {phase_sessions.SESSION_KEY: {"node_id": "fix", "claude_session_id": "cs-1"}}
    run = _run(_classes("bug-fix-reproduction"), "M", **last)  # escalated to M, back in fix after a red gate
    assert await shared_run_session(None, run, phases["fix"], TARGET) == ("cs-1", phase_sessions.RESUME_PHASE)
    assert await run_session.shared_run_session(None, run, phases["review"], TARGET) == ("", "")
