"""A size class may leave the system test out (``pipeline_scope``, data); the bug flow's S keeps it, and keeps the
hands-on test when the change touches what a person sees."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.services.workflow_runs.size_class.pipeline_scope import runs_system_test
from app.services.workflow_runs.size_class.schema import size_class_errors
from tests.scripted_pool_support import scripted_pool  # noqa: F401 - fixture

pytestmark = pytest.mark.usefixtures("scripted_pool")

SCOPE = {"system_test": "labels", "system_test_labels": ["ui-visible", "hands-on"]}


def _run(settings: dict, labels: list[str]) -> SimpleNamespace:
    return SimpleNamespace(context={"size_class": {"class": "S", "labels": labels, "classes": {"S": settings}}})


def test_the_system_test_runs_only_for_a_labelled_item_of_a_class_that_says_so():
    assert not runs_system_test(_run({"pipeline_scope": SCOPE}, []))
    assert runs_system_test(_run({"pipeline_scope": SCOPE}, ["UI-Visible"]))
    assert runs_system_test(_run({}, []))
    assert runs_system_test(SimpleNamespace(context={}))


def test_the_schema_names_a_wrong_scope():
    graph = SimpleNamespace(nodes={}, edges=[])
    block = {"default": "S", "rules": [], "classes": {"S": {"pipeline_scope": SCOPE}}}
    assert size_class_errors(block, graph) == []
    for wrong in ({"system_test": "sometimes"}, {"system_test": "labels"}, "labels"):
        errors = size_class_errors({**block, "classes": {"S": {"pipeline_scope": wrong}}}, graph)
        assert errors and "pipeline_scope" in errors[0]["message"]


def test_the_bug_flow_s_class_runs_the_system_test_and_the_hands_on_test_for_a_ui_change():
    import json
    from pathlib import Path

    seeds = json.loads((Path(__file__).parents[1] / "app/services/workflow_runs/seeds/phased_workflows.json")
                       .read_text(encoding="utf-8"))
    small = next(item for item in seeds if item["key"] == "bug-fix-reproduction")["definition"]["size_classes"][
        "classes"]["S"]
    assert small["pipeline_scope"]["system_test"] == "always"
    hands_on = next(skip for skip in small["skip_nodes"] if skip["node"] == "hands_on")
    assert hands_on["unless_changed"] == "ui_paths"


def _patch(*paths: str) -> str:
    return "".join(f"diff --git a/{path} b/{path}\n--- a/{path}\n+++ b/{path}\n@@ -1 +1 @@\n-a\n+b\n"
                   for path in paths)


@pytest.mark.parametrize(("paths", "kept"), [
    (["coffee/flutter/claude/lib/features/brews/presentation/brew_form_screen.dart",
      "coffee/flutter/claude/lib/features/equipment/domain/grinder_scale.dart"], True),
    (["coffee/flutter/claude/lib/features/equipment/domain/grinder_scale.dart",
      "coffee/flutter/claude/test/features/equipment/grinder_scale_test.dart"], False),
    (["e2e/python/split.py", "e2e/python/tests/test_split.py"], False),
    (["e2e/node/public/index.html"], True),
])
def test_the_hands_on_skip_of_class_s_keeps_the_step_for_a_change_a_person_sees(paths, kept):
    from app.services.workflow_runs.size_class.steps import _kept_by_change

    settings = {"skip_nodes": [{"node": "hands_on", "unless_changed": "ui_paths"}]}
    run = SimpleNamespace(context={"size_class": {"class": "S", "classes": {"S": settings}},
                                   "device_change": {"patch": _patch(*paths)}})
    assert bool(_kept_by_change(run, "hands_on")) is kept
    unreadable = SimpleNamespace(context={"size_class": {"class": "S", "classes": {"S": settings}}})
    assert _kept_by_change(unreadable, "hands_on")


@pytest.mark.asyncio
async def test_the_device_gets_only_the_unit_test_command_and_the_flag(db, monkeypatch):
    from app.services.workflow_runs import pipeline
    from tests.test_red_on_base import _at_pipeline_with_base_run
    from tests.workflow_run_pipeline_support import COMMANDS

    run, _session = await _at_pipeline_with_base_run(db, monkeypatch, {"pipeline_scope": SCOPE})
    view = pipeline.contract_view(run)
    assert view["commands"] == list(COMMANDS)[:1] and view["system_test"] is False
    assert view["red_on_base"]["tests"]


def test_the_devices_seconds_per_step_are_kept_and_nothing_else():
    from app.services.workflow_runs.pipeline_results import _timings

    assert _timings({"setup": 1.234, "red_on_base": 88, "total": 95.0, "evil": 3, "commands": -1, "tree": True}) == {
        "setup": 1.2, "red_on_base": 88.0, "total": 95.0}
    assert _timings("slow") == {}


def test_a_reported_build_reuse_is_kept_as_an_event_and_nothing_else(monkeypatch):
    from app.services.engineering_knowledge.stacks import build_artifacts
    from app.services.workflow_runs import build_cache

    flutter = next(item for item in build_artifacts() if item["tool"] == "flutter")
    assert flutter["args"] == ["build", "web"] and flutter["output"] == "build/web" and "lib" in flutter["inputs"]
    assert build_cache.view() == {"build_artifacts": build_artifacts()}
    events = []
    monkeypatch.setattr(build_cache, "record_event", lambda _db, _run, kind, **kw: events.append((kind, kw["detail"])))
    run = SimpleNamespace(current_node_id="pipeline")
    build_cache.record(None, run, {"build_cache": [
        {"result": "hit", "key": "a" * 64, "command": "flutter build web --release", "seconds": 0.07},
        {"result": "evil", "key": "b"}, "junk", {"result": "miss", "key": "c" * 64, "exit_code": 0, "rm": "-rf"}]})
    assert [(kind, detail["result"], detail["key"][:1]) for kind, detail in events] == [
        ("build_cache", "hit", "a"), ("build_cache", "miss", "c")]
    assert "rm" not in events[1][1]


def test_the_hands_on_view_names_how_many_scenarios_run_at_once():
    from app.services.engineering_knowledge.stacks import hands_on_workers

    assert hands_on_workers() == {"cores_per_worker": 3, "max": 4}
    assert hands_on_workers({"general": {"hands_on_workers": {"cores_per_worker": 0, "max": "4"}}}) == {}


def test_the_hands_on_view_names_the_browser_start_limit():
    from app.services.engineering_knowledge.stacks import browser_start_seconds

    assert browser_start_seconds() == 60
    assert browser_start_seconds({"general": {"browser_start_seconds": 2}}) == 0
