"""The fragment compiler: namespacing, node refs, instances, loops, gate checks, determinism."""

from __future__ import annotations

import copy
import json

from app.services.workflow_runs.fragments.compiler import compile_composite, composition_settings
from app.services.workflow_runs.fragments.format import (
    FRAGMENT_EDGES_KEY,
    ResolvedFragment,
    fragment_refs,
    parse_fragment,
)
from app.services.workflow_runs.fragments.node_refs import external_refs, rewrite_node_refs
from app.services.workflow_runs.handoff.contract import canonical_hash

GATE_CHECKS = [{"type": "tool_called", "blocking": True, "params": {"tools": ["submit_test_contract"], "min": 1}},
               {"type": "evidence_count", "params": {"min": 2}, "label": "Two ünïcode sources"}]


def toy_fragment(*, instance: str = "many") -> dict:
    """Every node-id-valued key (gate.phase, decision.source, review.producer, payload_from) and a bounded loop."""
    return {
        "execution_kind": "phased_fragment", "schema_version": "fragment/v1", "entry": "work",
        "ports": {"done": {"edge": "next", "accepts": "any"}, "stop": {"edge": "next", "accepts": "outcome"},
                  "again": {"edge": "loop", "accepts": "any"}},
        "requires": [], "provides": [], "instance": instance,
        "nodes": [
            {"id": "work", "type": "phase", "label": "Work", "config": {"agent": "a", "workflow_contract": {}}},
            {"id": "check", "type": "gate", "config": {"phase": "work", "checks": copy.deepcopy(GATE_CHECKS)}},
            {"id": "pick", "type": "decision", "config": {"source": "check", "options": ["passed"]}},
            {"id": "rev", "type": "review", "config": {"mode": "artefact", "kind": "spec", "source": "local_output",
                                                      "producer": "work"}},
            {"id": "show", "type": "user_confirmation", "config": {"subject": "ticket_draft", "payload_from": "work",
                                                                  "decider": "requester", "reminder_hours": 4}},
        ],
        "edges": [
            {"id": "e-work", "source_node_id": "work", "target_node_id": "check"},
            {"id": "e-check", "source_node_id": "check", "target_node_id": "pick", "when": "passed"},
            {"id": "loop-check", "source_node_id": "check", "target_node_id": "work", "when": "failed",
             "kind": "loop", "max_iterations": 3, "label": "Again"},
            {"id": "e-pick", "source_node_id": "pick", "target_node_id": "rev", "when": "passed"},
            {"id": "e-rev", "source_node_id": "rev", "target_node_id": "show"},
            {"id": "e-show", "source_node_id": "show", "target_port": "done", "when": "confirmed"},
            {"id": "e-stop", "source_node_id": "show", "target_port": "stop", "when": "stopped"},
            {"id": "loop-show", "source_node_id": "show", "target_port": "again", "when": "changed", "kind": "loop",
             "max_iterations": 2},
        ],
    }


def ref_node(node_id: str, fragment: dict, *, key: str = "toy", ports: dict | None = None, **config) -> dict:
    return {"id": node_id, "type": "fragment", "config": {
        "fragment_key": key, "fragment_checksum": canonical_hash(fragment),
        "ports": ports if ports is not None else {"done": "done", "stop": "stopped", "again": "ask"}, **config}}


def composite(*refs: dict, marker: bool = True) -> dict:
    """``start → ask → <refs in a row> … → done | stopped``; refs are chained through their ``done`` ports."""
    edges: list[dict] = [{"id": "e-start", "source_node_id": "start", "target_node_id": "ask"},
                         {"id": "e-ask", "source_node_id": "ask", "target_node_id": refs[0]["id"],
                          "when": "confirmed"},
                         {"id": "e-ask-stop", "source_node_id": "ask", "target_node_id": "stopped", "when": "stopped"}]
    if marker:
        edges += [{FRAGMENT_EDGES_KEY: ref["id"]} for ref in refs]
    return {"execution_kind": "phased", "plan_node": "", "budget": {"tool_calls": 9},
            "nodes": [{"id": "start", "type": "start"},
                      {"id": "ask", "type": "user_confirmation", "config": {"subject": "advance"}}, *refs,
                      {"id": "done", "type": "outcome", "config": {"outcome": "done"}},
                      {"id": "stopped", "type": "outcome", "config": {"outcome": "stopped"}}],
            "edges": edges}


def resolve(source: dict, fragments: dict[str, dict], *, version: int = 1) -> dict[str, ResolvedFragment]:
    """Resolve every reference of ``source`` from ``fragments`` (key → definition), as the store would."""
    return {ref.node_id: ResolvedFragment(key=ref.fragment_key, version_id=f"{ref.fragment_key}-v{version}",
                                          version=version, checksum=canonical_hash(fragments[ref.fragment_key]),
                                          definition=parse_fragment(fragments[ref.fragment_key]))
            for ref in fragment_refs(source)}


def _node(definition: dict, node_id: str) -> dict:
    return next(node for node in definition["nodes"] if node["id"] == node_id)


def test_the_default_namespace_renames_nodes_edges_and_every_node_ref_key():
    fragment = toy_fragment()
    source = composite(ref_node("probe", fragment))
    compiled = compile_composite(source, resolve(source, {"toy": fragment})).definition
    ids = [node["id"] for node in compiled["nodes"]]
    assert ids == ["start", "ask", "probe.work", "probe.check", "probe.pick", "probe.rev", "probe.show", "done",
                   "stopped"]
    assert _node(compiled, "probe.check")["config"]["phase"] == "probe.work"
    assert _node(compiled, "probe.pick")["config"]["source"] == "probe.check"
    assert _node(compiled, "probe.rev")["config"]["producer"] == "probe.work"
    assert _node(compiled, "probe.rev")["config"]["source"] == "local_output"  # not a node ref: unchanged
    assert _node(compiled, "probe.show")["config"]["payload_from"] == "probe.work"
    edges = {edge["id"]: edge for edge in compiled["edges"]}
    assert edges["e-ask"]["target_node_id"] == "probe.work"  # into the reference → the namespaced entry
    assert edges["probe.e-check"] == {"id": "probe.e-check", "source_node_id": "probe.check",
                                      "target_node_id": "probe.pick", "when": "passed"}
    assert edges["probe.e-show"]["target_node_id"] == "done"  # a port → the composite node it maps to
    assert edges["probe.loop-show"]["target_node_id"] == "ask"
    assert not any(node["type"] == "fragment" for node in compiled["nodes"])
    assert not any(FRAGMENT_EDGES_KEY in edge for edge in compiled["edges"])
    # Definition-level keys come from the source; the fragment carries none.
    assert (compiled["execution_kind"], compiled["plan_node"], compiled["budget"]) == ("phased", "", {"tool_calls": 9})


def test_two_instances_of_a_many_fragment_are_collision_free():
    fragment = toy_fragment(instance="many")
    first = ref_node("one", fragment, ports={"done": "two", "stop": "stopped", "again": "ask"})
    second = ref_node("two", fragment)
    source = composite(first, second)
    composition = compile_composite(source, resolve(source, {"toy": fragment}))
    ids = [node["id"] for node in composition.definition["nodes"]]
    assert len(ids) == len(set(ids)) and {"one.work", "two.work"} <= set(ids)
    assert {edge["id"]: edge for edge in composition.definition["edges"]}["one.e-show"]["target_node_id"] == "two.work"
    assert [item["ref"] for item in composition.fragments] == ["one", "two"]
    assert composition.provenance["two.check"]["node"] == "check"


def test_loop_edges_inside_a_fragment_keep_max_iterations_and_gate_checks_are_byte_identical():
    fragment = toy_fragment()
    source = composite(ref_node("probe", fragment))
    compiled = compile_composite(source, resolve(source, {"toy": fragment})).definition
    edges = {edge["id"]: edge for edge in compiled["edges"]}
    assert (edges["probe.loop-check"]["kind"], edges["probe.loop-check"]["max_iterations"]) == ("loop", 3)
    assert edges["probe.loop-check"]["label"] == "Again"
    assert edges["probe.loop-show"]["max_iterations"] == 2
    checks = _node(compiled, "probe.check")["config"]["checks"]
    assert json.dumps(checks, ensure_ascii=False) == json.dumps(GATE_CHECKS, ensure_ascii=False)
    show = _node(compiled, "probe.show")["config"]
    assert (show["decider"], show["reminder_hours"]) == ("requester", 4)
    assert _node(compiled, "probe.work")["config"] == {"agent": "a", "workflow_contract": {}}


def test_without_a_marker_the_fragment_edges_are_appended():
    fragment = toy_fragment()
    source = composite(ref_node("probe", fragment), marker=False)
    compiled = compile_composite(source, resolve(source, {"toy": fragment})).definition
    assert [edge["id"] for edge in compiled["edges"][:3]] == ["e-start", "e-ask", "e-ask-stop"]
    assert [edge["id"] for edge in compiled["edges"][3:]] == [f"probe.{edge['id']}" for edge in fragment["edges"]]


def test_the_compile_is_deterministic_and_never_mutates_its_inputs():
    fragment = toy_fragment()
    source = composite(ref_node("probe", fragment))
    before = copy.deepcopy((source, fragment))
    first = compile_composite(source, resolve(source, {"toy": fragment}))
    second = compile_composite(copy.deepcopy(source), resolve(source, {"toy": copy.deepcopy(fragment)}))
    assert canonical_hash(first.definition) == canonical_hash(second.definition)
    assert first.compiled_digest == second.compiled_digest and first.source_hash == second.source_hash
    assert composition_settings(first, source) == composition_settings(second, source)
    assert (source, fragment) == before
    first.definition["nodes"][2]["config"]["agent"] = "changed"
    assert fragment["nodes"][0]["config"]["agent"] == "a"  # the compiled graph shares nothing with the fragment


def test_node_refs_rewrite_is_a_deep_copy_and_external_refs_leave_the_fragment():
    node = {"id": "check", "type": "gate", "config": {"phase": "work", "checks": [{"type": "ci_green"}]}}
    renamed = rewrite_node_refs(node, lambda value: f"x.{value}")
    assert renamed["config"]["phase"] == "x.work" and node["config"]["phase"] == "work"
    assert renamed["config"]["checks"] is not node["config"]["checks"]
    assert external_refs(node, {"check"}) == ["work"] and external_refs(node, {"work"}) == []
    phase_less_gate = {"id": "g", "type": "gate", "config": {"checks": []}}  # the last phase: no ref at all
    assert external_refs(phase_less_gate, set()) == []
    other_kind = {"id": "p", "type": "platform_action", "config": {"source": "elsewhere"}}
    assert external_refs(other_kind, set()) == []  # only the closed (kind, key) pairs name nodes
