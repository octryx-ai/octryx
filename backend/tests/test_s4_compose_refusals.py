"""Refusals of a composite: one case per code, and the phased laws over the composed graph.

The compiler refuses pins, ports, ids, nesting, single instances, exits and markers with its own codes; the
composed graph is then judged by the unchanged phased validator, so a ``next`` port back to an ancestor is a
``cycle_without_loop_edge`` and a loop port to a node that is not earlier is a ``loop_not_back_edge``.
"""

from __future__ import annotations

import copy

import pytest

from app.services.workflow_runs.fragments.compiler import compile_composite
from app.services.workflow_runs.fragments.format import (
    FRAGMENT_EDGES_KEY,
    FragmentDefinition,
    FragmentError,
    FragmentPort,
    ResolvedFragment,
    fragment_refs,
    parse_fragment,
)
from app.services.workflow_runs.fragments.validation import validate_composition, validate_fragment_definition
from app.services.workflow_runs.handoff.contract import canonical_hash
from tests.test_s4_compiler import composite, ref_node, resolve
from tests.test_s4_sf5_equivalence import b_source, resolved_sf5


def confirm_fragment(*, instance: str = "many", requires: list[str] | None = None, node_id: str = "confirm") -> dict:
    """The acceptance probe: one ``advance`` confirmation, ports go (next), stop (outcome), back (loop)."""
    return {
        "execution_kind": "phased_fragment", "schema_version": "fragment/v1", "entry": node_id,
        "ports": {"go": {"edge": "next", "accepts": "any"}, "stop": {"edge": "next", "accepts": "outcome"},
                  "back": {"edge": "loop", "accepts": "any"}},
        "requires": requires or [], "provides": [], "instance": instance,
        "nodes": [{"id": node_id, "type": "user_confirmation", "label": "Go on?", "config": {"subject": "advance"}}],
        "edges": [{"id": "e-go", "source_node_id": node_id, "target_port": "go", "when": "confirmed"},
                  {"id": "e-stop", "source_node_id": node_id, "target_port": "stop", "when": "stopped"},
                  {"id": "loop-back", "source_node_id": node_id, "target_port": "back", "when": "changed",
                   "kind": "loop", "max_iterations": 2}],
    }


PORTS = {"go": "done", "stop": "stopped", "back": "ask"}


def probe(*, fragment: dict | None = None, ports: dict | None = None, **config) -> tuple[dict, dict]:
    fragment = fragment or confirm_fragment()
    source = composite(ref_node("probe", fragment, ports=dict(PORTS if ports is None else ports), **config))
    return source, fragment


def _compile_codes(source: dict, resolved: dict) -> list[str]:
    with pytest.raises(FragmentError) as raised:
        compile_composite(source, resolved)
    return [item["code"] for item in raised.value.errors]


def _codes(source: dict, fragment: dict) -> list[str]:
    return _compile_codes(source, resolve(source, {"toy": fragment}))


def _report_codes(source: dict, resolved: dict) -> list[str]:
    return [item["code"] for item in validate_composition(source, resolved)["errors"]]


def test_the_probe_composite_is_valid_so_every_refusal_below_is_its_own():
    source, fragment = probe()
    report = validate_composition(source, resolve(source, {"toy": fragment}))
    assert report["valid"], report["errors"]
    assert [node["id"] for node in compile_composite(source, resolve(source, {"toy": fragment})).definition[
        "nodes"]] == ["start", "ask", "probe.confirm", "done", "stopped"]


# Pins -------------------------------------------------------------------------------------------------------------

def test_a_missing_or_malformed_pin_is_refused():
    source, _fragment = probe()
    del source["nodes"][2]["config"]["fragment_checksum"]
    with pytest.raises(FragmentError) as raised:
        fragment_refs(source)
    assert [item["code"] for item in raised.value.errors] == ["fragment_pin_missing"]
    source, _fragment = probe(fragment_checksum="sha256:short")
    assert _report_codes(source, {}) == ["fragment_pin_missing"]
    source, _fragment = probe(fragment_version_id="")
    assert _report_codes(source, {}) == ["fragment_pin_missing"]


def test_an_unresolved_or_changed_pin_is_refused():
    source, fragment = probe()
    assert _compile_codes(source, {}) == ["fragment_pin_unresolved"]
    changed = copy.deepcopy(fragment)
    changed["nodes"][0]["label"] = "Continue?"
    stale = {"probe": ResolvedFragment("toy", "toy-v2", 2, canonical_hash(changed), parse_fragment(changed))}
    assert _compile_codes(source, stale) == ["fragment_pin_changed"]
    source, fragment = probe(fragment_version_id="toy-v1")
    other_version = {"probe": ResolvedFragment("toy", "toy-v2", 2, canonical_hash(fragment), parse_fragment(fragment))}
    assert _compile_codes(source, other_version) == ["fragment_pin_changed"]
    wrong_key = {"probe": ResolvedFragment("other", "toy-v1", 1, canonical_hash(fragment), parse_fragment(fragment))}
    assert _compile_codes(source, wrong_key) == ["fragment_pin_unresolved"]


def test_an_invalid_namespace_is_refused():
    source, fragment = probe(namespace="Bad-Name.")
    assert _report_codes(source, {}) == ["fragment_namespace"]


# Ports ------------------------------------------------------------------------------------------------------------

def test_an_unmapped_port_is_refused():
    source, fragment = probe(ports={"go": "done", "back": "ask"})
    assert _codes(source, fragment) == ["fragment_port_unmapped"]


def test_an_unknown_port_is_refused():
    source, fragment = probe(ports={**PORTS, "extra": "done"})
    assert _codes(source, fragment) == ["fragment_port_unknown"]


def test_a_port_to_an_unknown_node_is_refused():
    source, fragment = probe(ports={**PORTS, "go": "nowhere"})
    assert _codes(source, fragment) == ["fragment_port_target_unknown"]


def test_a_port_to_a_node_of_the_wrong_kind_is_refused():
    source, fragment = probe(ports={**PORTS, "stop": "ask"})  # accepts: outcome → a confirmation
    assert _codes(source, fragment) == ["fragment_port_target_kind"]
    # accepts: pause → an outcome (SF-5's failed port mapped to B's 'blocked' outcome).
    assert _compile_codes(b_source(ports={"proven": "acceptance_open", "failed": "blocked", "stopped": "stopped",
                                          "rework": "doc_final"}), resolved_sf5()) == ["fragment_port_target_kind"]


def test_a_loop_port_to_a_node_that_is_not_earlier_is_loop_not_back_edge():
    source, fragment = probe(ports={**PORTS, "back": "done"})
    codes = _report_codes(source, resolve(source, {"toy": fragment}))
    assert "loop_not_back_edge" in codes and not any(code.startswith("fragment_") for code in codes)


# Cycles -----------------------------------------------------------------------------------------------------------

def test_a_next_port_back_to_an_ancestor_is_a_cycle_between_fragments():
    source, fragment = probe(ports={**PORTS, "go": "ask"})
    assert "cycle_without_loop_edge" in _report_codes(source, resolve(source, {"toy": fragment}))


def test_a_fragment_with_a_next_cycle_is_refused():
    fragment = confirm_fragment()
    fragment["nodes"].append({"id": "again", "type": "user_confirmation", "config": {"subject": "advance"}})
    fragment["edges"][0] = {"id": "e-go", "source_node_id": "confirm", "target_node_id": "again", "when": "confirmed"}
    fragment["edges"] += [{"id": "e-again", "source_node_id": "again", "target_node_id": "confirm",
                           "when": "confirmed"},
                          {"id": "e-again-go", "source_node_id": "again", "target_port": "go", "when": "changed"},
                          {"id": "e-again-stop", "source_node_id": "again", "target_port": "stop", "when": "stopped"}]
    report = validate_fragment_definition(fragment)
    assert not report["valid"] and "cycle_without_loop_edge" in [item["code"] for item in report["errors"]]


# Ids --------------------------------------------------------------------------------------------------------------

def test_an_id_collision_with_the_empty_namespace_is_refused():
    source, fragment = probe(namespace="", ports=PORTS)
    source["nodes"].insert(1, {"id": "confirm", "type": "user_confirmation", "config": {"subject": "advance"}})
    assert _codes(source, fragment) == ["fragment_id_collision"]
    # The same fragment under its default namespace is collision-free.
    source, fragment = probe()
    source["nodes"].insert(1, {"id": "confirm", "type": "user_confirmation", "config": {"subject": "advance"}})
    assert compile_composite(source, resolve(source, {"toy": fragment})).definition


def test_two_references_with_one_id_collide():
    fragment = confirm_fragment()
    source = composite(ref_node("probe", fragment, ports=PORTS), ref_node("probe", fragment, ports=PORTS))
    assert "fragment_id_collision" in _report_codes(source, resolve(source, {"toy": fragment}))


def test_a_compiled_node_id_longer_than_128_characters_is_refused():
    fragment = confirm_fragment(node_id="c" * 100)
    source, fragment = probe(fragment=fragment, namespace="n" * 32 + ".")
    assert _codes(source, fragment) == ["fragment_node_id_too_long"]


# Nesting, instances, exits, markers -------------------------------------------------------------------------------

def test_nesting_is_refused_in_the_format_and_in_the_compiler():
    nested = confirm_fragment()
    nested["nodes"].append({"id": "inner", "type": "fragment", "config": {}})
    with pytest.raises(FragmentError) as raised:
        parse_fragment(nested)
    assert "fragment_nested" in [item["code"] for item in raised.value.errors]
    source, fragment = probe()
    parsed = parse_fragment(fragment)
    smuggled = FragmentDefinition(entry=parsed.entry, ports=parsed.ports, requires=parsed.requires,
                                  provides=parsed.provides, instance=parsed.instance,
                                  nodes=(*parsed.nodes, {"id": "inner", "type": "fragment", "config": {}}),
                                  edges=parsed.edges, raw=parsed.raw)
    resolved = {"probe": ResolvedFragment("toy", "toy-v1", 1, canonical_hash(fragment), smuggled)}
    assert _compile_codes(source, resolved) == ["fragment_nested"]


def test_a_single_instance_fragment_is_referenced_once():
    fragment = confirm_fragment(instance="single")
    first = ref_node("one", fragment, ports={**PORTS, "go": "two"})
    source = composite(first, ref_node("two", fragment, ports=PORTS))
    assert _codes(source, fragment) == ["fragment_single_instance"]
    many = confirm_fragment(instance="many")
    source = composite(ref_node("one", many, ports={**PORTS, "go": "two"}), ref_node("two", many, ports=PORTS))
    assert validate_composition(source, resolve(source, {"toy": many}))["valid"]


def test_the_reference_node_has_no_outgoing_edges():
    source, fragment = probe()
    source["edges"].append({"id": "e-probe", "source_node_id": "probe", "target_node_id": "done"})
    assert _codes(source, fragment) == ["fragment_ref_exit"]


def test_an_unknown_or_duplicate_marker_is_refused():
    source, fragment = probe()
    source["edges"].append({FRAGMENT_EDGES_KEY: "ghost"})
    assert _codes(source, fragment) == ["fragment_marker_unknown"]
    source, fragment = probe()
    source["edges"].append({FRAGMENT_EDGES_KEY: "probe"})
    assert _codes(source, fragment) == ["fragment_marker_duplicate"]


# Inputs -----------------------------------------------------------------------------------------------------------

def test_a_required_input_not_produced_before_the_entry_is_refused():
    fragment = confirm_fragment(requires=["feature_documentation"])
    source, fragment = probe(fragment=fragment)
    assert _codes(source, fragment) == ["fragment_input_missing"]
    report = validate_composition(source, resolve(source, {"toy": fragment}))
    assert [item["code"] for item in report["errors"]] == ["fragment_input_missing"]
    assert report["composition"]["compiled_digest"]  # the compiled graph was still judged


def test_sf5_in_b_needs_the_final_documentation_before_its_entry():
    assert "fragment_input_missing" not in _report_codes(b_source(), resolved_sf5())
    # Without the documentation phases nothing before the entry produces feature_documentation.
    source = b_source()
    source["nodes"] = [node for node in source["nodes"] if node["id"] not in {"doc_draft", "doc_final"}]
    codes = _report_codes(source, resolved_sf5())
    assert "fragment_input_missing" in codes


def test_a_failed_compile_still_reports_the_composition_block():
    source, fragment = probe(ports={"go": "done"})
    report = validate_composition(source, resolve(source, {"toy": fragment}))
    assert not report["valid"] and report["composition"]["fragments"] == []
    assert report["composition"]["source_hash"] == canonical_hash(source)


def test_a_loop_port_accepts_any_only():
    fragment = confirm_fragment()
    fragment["ports"]["back"] = {"edge": "loop", "accepts": "pause"}
    assert "fragment_port_invalid" in [item["code"] for item in validate_fragment_definition(fragment)["errors"]]
    assert FragmentPort("back", "loop", "any") == parse_fragment(confirm_fragment()).ports["back"]
