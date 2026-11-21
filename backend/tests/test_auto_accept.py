"""The product owner answers at the start; a passed, fully verified story ships without a second question
."""

from __future__ import annotations

from types import SimpleNamespace

from app.services.workflow_runs.auto_accept import accept_reason


def _run(verdict="pass", findings=(), statuses=("verified", "verified")):
    tasks = [{"id": f"T{n}", "text": "x", "proof": f"tests/a.py::test_{n}", "status": status}
             for n, status in enumerate(statuses, 1)]
    return SimpleNamespace(context={"review": {"verdict": verdict, "findings": list(findings)}, "task_list": tasks})


def test_only_a_passed_review_with_every_task_verified_ships_by_itself():
    assert accept_reason(_run()) == "review passed, all 2 tasks verified"
    assert accept_reason(_run(verdict="changes")) == ""
    assert accept_reason(_run(findings=[{"severity": "medium", "fix": "T1: x"}])) == ""
    assert accept_reason(_run(findings=[{"severity": "low", "fix": "naming"}])) != ""
    assert accept_reason(_run(statuses=("verified", "done"))) == ""
    assert accept_reason(_run(statuses=())) == ""  # no task list: the product owner decides
