"""A merged phase may do what either phase it holds may do: the fix phase's ``protect_confirmed_tests`` must not
refuse every test file, or class S could never write its reproduction. Only the tests the platform confirmed stay
locked. A refusal rule that sends the run back to a phase merged into the current one goes on in the same turn
instead of pausing and restarting it."""

from __future__ import annotations

import copy
import json

import pytest

from app.services.workflow_runs.octryx.phase_rules import _path_decision
from app.services.workflow_runs.path_rules import PROTECT_CONFIRMED_TESTS, WRITE_TESTS
from app.services.workflow_runs.protected_paths import path_matches, protected_kind
from app.services.workflow_runs.seeding import SEEDS_PATH
from app.services.workflow_runs.size_class.merge import merged_config

ROOT = "/repo"
SAMPLES = ["e2e/python/tests/test_split.py", "e2e/node/test/books.test.js", "e2e/python/splitbill/core.py",
           "e2e/node/src/books.js", "tests/test_new_case.py", "src/app/main.py"]


def _rules(config: dict) -> dict:
    return dict(dict(config.get("workflow_contract") or {}).get("path_rules") or {})


def _allowed(rules: dict, path: str, confirmed: list[str]) -> bool:
    write = list(rules.get("write") or [])
    if write and not any(path_matches(path, pattern) for pattern in write):
        return False
    return protected_kind(path, confirmed_files=confirmed, protect_tests=rules.get(PROTECT_CONFIRMED_TESTS) is True,
                          exists=True, tests_free=rules.get(WRITE_TESTS) is True) is None


def _seed_merges() -> list[tuple[str, dict, dict]]:
    found = []
    for workflow in json.loads(SEEDS_PATH.read_text(encoding="utf-8")):
        definition = dict(workflow.get("definition") or {})  # a composed one (definition_source) merges nothing
        nodes = {node["id"]: node for node in definition.get("nodes") or []}
        for settings in dict(dict(definition.get("size_classes") or {}).get("classes") or {}).values():
            for source, target in dict(settings.get("merge") or {}).items():
                found.append((f"{workflow['key']}:{source}->{target}", nodes[source]["config"], nodes[target]["config"]))
    return found


def test_a_merge_loses_no_right_of_either_phase():
    merges = _seed_merges()
    assert merges, "the shipped workflows merge phases (bug S); the guard must see them"
    for name, first, second in merges:
        merged = merged_config(first, second)
        allow = set(merged["tool_policy"]["allowlist"])
        for config in (first, second):
            assert set(config["tool_policy"].get("allowlist") or []) <= allow, name
            assert not allow & set(merged["tool_policy"].get("denylist") or []), name
        for path in SAMPLES:
            if _allowed(_rules(first), path, []) or _allowed(_rules(second), path, []):
                assert _allowed(_rules(merged), path, []), (name, path)
        if _rules(second).get(PROTECT_CONFIRMED_TESTS) is True:  # the later phase's lock on confirmed tests stays
            assert not _allowed(_rules(merged), SAMPLES[0], [SAMPLES[0]]), name


def _merged_fix_phase(confirmed: list[str]) -> dict:
    first, second = next((first, second) for name, first, second in _seed_merges()
                         if name.startswith("bug-fix-reproduction:reproduce->fix"))
    rules = _rules(merged_config(copy.deepcopy(first), copy.deepcopy(second)))
    return {"title": "Minimal fix", "protected_files": confirmed,
            "path_rules": {"write": list(rules.get("write") or []), "create": list(rules.get("create") or []),
                           "protect_confirmed_tests": rules.get(PROTECT_CONFIRMED_TESTS) is True,
                           "write_tests": rules.get(WRITE_TESTS) is True}}


@pytest.mark.parametrize("test_file", ["e2e/python/tests/test_split.py", "e2e/node/test/books.test.js"])
def test_the_merged_fix_writes_its_failing_test_and_cannot_change_it_once_confirmed(test_file):
    edit = {"file_path": f"{ROOT}/{test_file}"}
    facts = {"target_exists": True, "shadows_installed": False}
    assert _path_decision(_merged_fix_phase([]), edit, ROOT, ROOT, facts) is None
    refused = _path_decision(_merged_fix_phase([test_file]), edit, ROOT, ROOT, facts)
    assert refused is not None and "confirmed" in refused.message


@pytest.mark.asyncio
async def test_going_back_to_a_phase_merged_into_this_one_goes_on_in_the_same_turn(db):
    from app.services.workflow_runs.records import start_run
    from app.services.workflow_runs.refusals import ACTION_CONTINUE, react
    from tests.phased_workflow_fixtures import admin_user, publish_phased, run_workspace
    from tests.test_workflow_size_class_merge import MERGE, _definition

    definition = _definition(MERGE)
    make = next(node for node in definition["nodes"] if node["id"] == "make")
    make["config"]["refusals"] = [{"reason": "protected_path", "repeat": 1, "action": {"change_plan": "write"}}]
    workspace_id = await run_workspace(db, await admin_user(db))
    run = await start_run(db, user=await admin_user(db), workflow_key=await publish_phased(db, definition),
                          project_id=workspace_id)
    assert run.current_node_id == "make"
    taken = await react(db, run, tool="Edit", reason="protected_path", tool_input={"file_path": "tests/test_x.py"})
    assert taken == ACTION_CONTINUE
    assert (run.status, run.pause_reason, run.current_node_id) == ("running", None, "make")
    assert "refusal_change_plan" not in dict(run.context or {})


CONFIRMING = frozenset({"tests_green", "confirmed_tests_intact", "reproduces", "tests_red"})


def test_every_gate_after_a_merge_gets_the_confirmation_the_skipped_steps_gave():
    """A gate after the merged phase that judges confirmed tests (``green``) gets them in merge mode: the merged phase
    submits the reproduction the platform binds itself (``merge.confirm_in_turn``) and the class proves it on the
    base commit (without it there are no confirmed tests and green fails at every turn's end)."""
    from app.services.workflow_runs.size_class.merge import merged_config

    checked = 0
    for workflow in json.loads(SEEDS_PATH.read_text(encoding="utf-8")):
        definition = dict(workflow.get("definition") or {})
        nodes = {node["id"]: node for node in definition.get("nodes") or []}
        edges = [edge for edge in definition.get("edges") or [] if edge.get("kind") != "loop"]
        for name, settings in dict(dict(definition.get("size_classes") or {}).get("classes") or {}).items():
            for source, target in dict(settings.get("merge") or {}).items():
                later, frontier = set(), [target]
                while frontier:
                    for edge in edges:
                        if edge["source_node_id"] == frontier[-1] and edge["target_node_id"] not in later:
                            later.add(edge["target_node_id"])
                            frontier.insert(0, edge["target_node_id"])
                    frontier.pop()
                judged = [node_id for node_id in later if nodes[node_id].get("type") == "gate" and any(
                    check.get("type") in CONFIRMING for check in nodes[node_id]["config"].get("checks") or [])]
                if not judged:
                    continue
                checked += 1
                merged = merged_config(nodes[source]["config"], nodes[target]["config"])
                where = f"{workflow['key']} class {name}: {source} into {target}, gates {judged}"
                assert merged.get("output") == "reproduction", where
                assert settings.get("red_on_base") is True, where
    assert checked, "the shipped bug flow merges reproduce into fix before its green gate"
