"""The fragment format and its harness validation: the same phased validator judges a fragment."""

from __future__ import annotations

import copy

import pytest

from app.services.workflow_runs.fragments.format import (
    FRAGMENT_KIND,
    FRAGMENT_NODE_KINDS,
    FragmentError,
    fragment_refs,
    is_composite_source,
    is_fragment_definition,
    parse_fragment,
)
from app.services.workflow_runs.fragments.validation import harness_definition, validate_fragment_definition
from app.services.workflow_runs.graph import NODE_KINDS
from tests.test_s4_compose_refusals import confirm_fragment
from tests.test_s4_sf5_equivalence import b_source, sf5_v1


def _codes(definition: dict) -> list[str]:
    return [item["code"] for item in validate_fragment_definition(definition)["errors"]]


def test_the_harness_accepts_sf5_v1():
    report = validate_fragment_definition(sf5_v1())
    assert report["valid"], report["errors"]
    assert report["execution_kind"] == FRAGMENT_KIND and report["ports"] == ["failed", "proven", "rework", "stopped"]
    harness = harness_definition(parse_fragment(sf5_v1()))
    assert harness["nodes"][0] == {"id": "__start", "type": "start"}
    assert {node["id"] for node in harness["nodes"] if node["id"].startswith("__")} == {
        "__start", "__pause_failed", "__end", "__end_proven", "__end_stopped"}
    rework = next(edge for edge in harness["edges"] if edge["id"] == "loop-publication")
    assert (rework["target_node_id"], rework["max_iterations"]) == ("__start", 2)


def test_kind_markers():
    assert FRAGMENT_NODE_KINDS == NODE_KINDS - {"start", "outcome", "pause"}
    assert is_fragment_definition(sf5_v1()) and not is_fragment_definition(b_source())
    assert is_composite_source(b_source()) and not is_composite_source(sf5_v1())
    assert not is_composite_source({"execution_kind": "phased", "nodes": [], "edges": []})
    assert is_composite_source({"execution_kind": "phased", "nodes": [], "edges": [{"fragment_edges": "x"}]})


@pytest.mark.parametrize("kind", ["start", "outcome", "pause"])
def test_a_start_outcome_or_pause_inside_is_refused(kind: str):
    fragment = sf5_v1()
    fragment["nodes"].append({"id": "own", "type": kind, "config": {}})
    assert _codes(fragment) == ["fragment_node_kind"]


def test_an_external_node_ref_is_refused():
    fragment = sf5_v1()
    fragment["nodes"].append({"id": "pick", "type": "decision", "config": {"source": "accept_functional",
                                                                            "options": ["accepted"]}})
    fragment["edges"].append({"id": "e-pick", "source_node_id": "pick", "target_port": "proven", "when": "accepted"})
    assert "fragment_external_ref" in _codes(fragment)


def test_an_unused_port_is_refused():
    fragment = sf5_v1()
    fragment["ports"]["spare"] = {"edge": "next", "accepts": "any"}
    assert _codes(fragment) == ["fragment_port_unused"]


def test_a_provides_the_fragment_does_not_produce_is_refused():
    fragment = sf5_v1()
    fragment["provides"] = ["change_plan"]
    assert _codes(fragment) == ["fragment_provides"]
    fragment["provides"] = []
    fragment["requires"] = ["no_such_kind"]
    assert _codes(fragment) == ["fragment_requires"]


def test_requires_covers_a_consumer_the_composite_feeds():
    fragment = confirm_fragment()
    fragment["nodes"][0]["config"] = {"subject": "reproduction"}  # consumes reproduction
    assert "consumer_without_producer" in _codes(fragment)
    fragment["requires"] = ["reproduction"]
    assert validate_fragment_definition(fragment)["valid"]


def test_the_phased_laws_apply_inside_a_fragment():
    fragment = sf5_v1()
    fragment["edges"] = [edge for edge in fragment["edges"] if edge["id"] != "e-reserve-ko"]
    assert _codes(fragment) == ["missing_failure_route"]
    fragment = sf5_v1()
    next(edge for edge in fragment["edges"] if edge["id"] == "loop-publication").pop("max_iterations")
    assert _codes(fragment) == ["unbounded_loop"]
    fragment = sf5_v1()
    next(edge for edge in fragment["edges"] if edge["id"] == "e-publication-stopped")["when"] = "maybe"
    assert _codes(fragment) == ["unknown_route"]


@pytest.mark.parametrize(("mutate", "code"), [
    (lambda f: f.update(execution_kind="phased"), "fragment_kind"),
    (lambda f: f.update(schema_version="fragment/v2"), "fragment_schema"),
    (lambda f: f.update(entry="acceptance_open"), "fragment_entry"),
    (lambda f: f.update(instance="twice"), "fragment_instance"),
    (lambda f: f.update(plan_node="clarify"), "fragment_definition_key"),
    (lambda f: f["ports"].update(proven={"edge": "jump", "accepts": "any"}), "fragment_port_invalid"),
    (lambda f: f["edges"][0].update(target_port="proven"), "fragment_edge_target"),
    (lambda f: f["edges"][0].update(target_node_id="acceptance_open"), "fragment_edge_target"),
    (lambda f: f["edges"][-1].update(target_port="ghost"), "fragment_port_unknown"),
    (lambda f: f["edges"][-1].update(target_port="rework"), "fragment_port_edge"),
    (lambda f: f["nodes"].append(copy.deepcopy(f["nodes"][0])), "fragment_id_collision"),
])
def test_structural_refusals(mutate, code: str):
    fragment = sf5_v1()
    mutate(fragment)
    with pytest.raises(FragmentError) as raised:
        parse_fragment(fragment)
    assert code in [item["code"] for item in raised.value.errors]
    assert code in _codes(fragment)


def test_a_reference_defaults_its_namespace_to_its_id():
    source = b_source()
    del source["nodes"][23]["config"]["namespace"]
    [ref] = fragment_refs(source)
    assert (ref.node_id, ref.namespace, ref.version_id, ref.index) == ("publish_prove", "publish_prove.", None, 23)
    source["nodes"][23]["config"]["ports"] = ["proven"]
    with pytest.raises(FragmentError) as raised:
        fragment_refs(source)
    assert [item["code"] for item in raised.value.errors] == ["fragment_ref_invalid"]
