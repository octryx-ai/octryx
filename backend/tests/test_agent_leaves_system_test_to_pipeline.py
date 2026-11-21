"""An agent must not run the system test right before the pipeline that always runs it, nor spend many calls
looking for a red Flutter test's message in the short output. A class with "agent_system_test": "pipeline"
leaves the system test to the pipeline; every runner's hint says how to see one red test's message
(stacks.json failure_hint)."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from app.services.workflow_runs.size_class.pipeline_scope import agent_runs_system_test
from app.services.workflow_runs.size_class.schema import size_class_errors


def _run(settings: dict) -> SimpleNamespace:
    return SimpleNamespace(context={"size_class": {"class": "M", "classes": {"M": settings}}})


def test_the_class_decides_whether_the_agent_runs_the_system_test_itself():
    assert agent_runs_system_test(_run({}))  # default:
    assert not agent_runs_system_test(_run({"pipeline_scope": {"agent_system_test": "pipeline"}}))
    graph = SimpleNamespace(nodes={}, edges=[])
    bad = {"default": "M", "rules": [], "classes": {"M": {"pipeline_scope": {"agent_system_test": "never"}}}}
    assert "agent_system_test" in size_class_errors(bad, graph)[0]["message"]


def test_the_shipped_bug_and_epic_classes_leave_it_to_the_pipeline_which_still_runs_it():
    seeds = json.loads((Path(__file__).parents[1] / "app/services/workflow_runs/seeds/phased_workflows.json")
                       .read_text(encoding="utf-8"))
    for key in ("bug-fix-reproduction", "epic-delivery"):
        classes = next(item for item in seeds if item["key"] == key)["definition"]["size_classes"]["classes"]
        for name, settings in classes.items():
            assert settings["pipeline_scope"] == {"system_test": "always", "agent_system_test": "pipeline"}, name


def test_the_runner_hint_says_how_to_see_one_red_test():
    from app.services.workflow_runs.octryx.phase_view import how_to_run_tests

    told = how_to_run_tests({"test": "flutter test"})
    assert "--reporter expanded" in told and r"grep -B2 -A30 '\[E\]'" in told  # Flutter marks a red test [E]
