"""Key proof: B's composite source with SF-5 v1 compiles back to exactly today's B.

SF-5 (publish & prove) is the bounded publication graph inside B: the 6 contiguous nodes ``reserve_publication`` …
``outsider_proof`` and their 14 contiguous edges. As fragment v1 they are verbatim; the four exits become ports
(``proven`` → ``acceptance_open``, ``failed`` → ``action_failed``, ``stopped`` → ``stopped``, the ``rework`` loop →
``doc_final``) and the namespace is ``""`` so the ids stay. B's source replaces them by one ``publish_prove``
reference (node index 23) and one edge marker (edge index 56). The compiler is order-preserving, so the compiled
graph equals B list-for-list and its digest is ``engineering_graph.BASE_DIGEST``.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

from app.services.workflow_runs.fragments.compiler import (
    COMPOSITION_SCHEMA,
    compile_composite,
    composition_settings,
    resolve_seed_fragments,
)
from app.services.workflow_runs.fragments.format import (
    FRAGMENT_EDGES_KEY,
    ResolvedFragment,
    fragment_refs,
    is_composite_source,
    is_fragment_definition,
    parse_fragment,
)
from app.services.workflow_runs.fragments.validation import validate_composition, validate_fragment_definition
from app.services.workflow_runs.graph_validation import validate_phased_definition
from app.services.workflow_runs.handoff.contract import canonical_hash
from app.services.workflow_runs.seeding import SEEDS_PATH, definition_digest
from tests.phased_seed_definitions import seed_definitions
from tests.specification_engineering_graph_support import BASE_DIGEST, BASE_KEY

SF5_KEY = "sf-publish-prove"
REF = "publish_prove"
SF5_NODES = ("reserve_publication", "confirm_publication", "publish_docs", "docs_in_knowledge", "audience_proof",
             "outsider_proof")
SF5_PORT_OF = {"acceptance_open": "proven", "action_failed": "failed", "stopped": "stopped", "doc_final": "rework"}
SF5_PORTS = {"proven": {"edge": "next", "accepts": "any"}, "failed": {"edge": "next", "accepts": "pause"},
             "stopped": {"edge": "next", "accepts": "outcome"}, "rework": {"edge": "loop", "accepts": "any"}}
FRAGMENTS_SEED_PATH = SEEDS_PATH.parent / "phased_fragments.json"


def b_definition() -> dict:
    """B as the seeds compile it."""
    return copy.deepcopy(next(item for item in seed_definitions() if item["key"] == BASE_KEY)["definition"])


def sf5_v1() -> dict:
    """SF-5 v1: B's 6 publication nodes and their 14 edges verbatim, the four exits as ports."""
    b = b_definition()
    edges = []
    for edge in b["edges"]:
        if edge["source_node_id"] not in SF5_NODES:
            continue
        edges.append({("target_port" if key == "target_node_id" and value not in SF5_NODES else key):
                      (SF5_PORT_OF[value] if key == "target_node_id" and value not in SF5_NODES else value)
                      for key, value in edge.items()})
    return {
        "execution_kind": "phased_fragment", "schema_version": "fragment/v1", "entry": "reserve_publication",
        "ports": copy.deepcopy(SF5_PORTS), "requires": ["feature_documentation"], "provides": [],
        "instance": "single", "nodes": [node for node in b["nodes"] if node["id"] in SF5_NODES], "edges": edges,
    }


def sf5_checksum() -> str:
    return canonical_hash(sf5_v1())


def b_source(*, ports: dict[str, str] | None = None, version_id: str | None = None) -> dict:
    """B as a composite source: one ``publish_prove`` reference at node 23, one edge marker at edge 56."""
    b = b_definition()
    config: dict = {"fragment_key": SF5_KEY, "fragment_checksum": sf5_checksum(), "namespace": "",
                    "ports": ports or {port: target for target, port in SF5_PORT_OF.items()}}
    if version_id is not None:
        config = {"fragment_key": SF5_KEY, "fragment_version_id": version_id, **config}
    index = [node["id"] for node in b["nodes"]].index(SF5_NODES[0])
    nodes = [node for node in b["nodes"] if node["id"] not in SF5_NODES]
    nodes.insert(index, {"id": REF, "type": "fragment", "label": "Publish & prove", "config": config})
    edges: list[dict] = []
    for edge in b["edges"]:
        if edge["source_node_id"] in SF5_NODES:
            if not any(FRAGMENT_EDGES_KEY in item for item in edges):
                edges.append({FRAGMENT_EDGES_KEY: REF})
            continue
        edges.append({**edge, "target_node_id": REF} if edge["target_node_id"] == SF5_NODES[0] else edge)
    return {**b, "nodes": nodes, "edges": edges}


def resolved_sf5(*, version_id: str = "", version: int = 1) -> dict[str, ResolvedFragment]:
    return {REF: ResolvedFragment(key=SF5_KEY, version_id=version_id, version=version, checksum=sf5_checksum(),
                                  definition=parse_fragment(sf5_v1()))}


def test_b_composite_source_compiles_back_to_exactly_todays_b():
    source = b_source()
    assert is_composite_source(source) and not is_composite_source(b_definition())
    assert (len(source["nodes"]), len(source["edges"])) == (41, 73)
    assert source["edges"][56] == {FRAGMENT_EDGES_KEY: REF}
    assert fragment_refs(source)[0].index == 23
    composition = compile_composite(source, resolved_sf5())
    assert composition.definition == b_definition()  # deep equality, list for list
    assert json.dumps(composition.definition) == json.dumps(b_definition())  # even the key order
    assert definition_digest(composition.definition) == BASE_DIGEST == composition.compiled_digest
    assert validate_phased_definition(composition.definition)["valid"]


def test_provenance_covers_exactly_the_six_nodes_and_fourteen_edges():
    composition = compile_composite(b_source(), resolved_sf5(version_id="v-1"))
    sf5_edges = [edge["id"] for edge in b_definition()["edges"] if edge["source_node_id"] in SF5_NODES]
    assert list(composition.provenance) == list(SF5_NODES)
    assert list(composition.edge_provenance) == sf5_edges and len(sf5_edges) == 14
    pin = {"ref": REF, "key": SF5_KEY, "version": 1, "version_id": "v-1", "checksum": sf5_checksum()}
    assert composition.provenance["confirm_publication"] == {**pin, "node": "confirm_publication"}
    assert composition.edge_provenance["loop-publication"] == {**pin, "edge": "loop-publication"}
    assert composition.fragments == [{**pin, "namespace": "", "nodes": list(SF5_NODES), "edges": sf5_edges}]
    settings = composition_settings(composition, b_source())
    assert settings["schema"] == COMPOSITION_SCHEMA and settings["source"] == b_source()
    assert settings["compiled_digest"] == BASE_DIGEST and settings["source_hash"] == canonical_hash(b_source())
    assert settings["provenance"] == composition.provenance


def test_sf5_v1_is_a_valid_fragment_and_the_composed_b_report_is_valid():
    assert is_fragment_definition(sf5_v1())
    report = validate_fragment_definition(sf5_v1())
    assert report["valid"], report["errors"]
    assert (report["node_count"], report["edge_count"], report["execution_kind"]) == (6, 14, "phased_fragment")
    composed = validate_composition(b_source(), resolved_sf5())
    assert composed["valid"], composed["errors"]
    assert composed["composition"]["compiled_digest"] == BASE_DIGEST
    [fragment] = composed["composition"]["fragments"]
    assert (fragment["deploy"], fragment["approval"], fragment["phase_classes"]) == (False, False, [])
    assert fragment["action_classes"]  # the publication actions' capability classes are listed


def test_the_seed_path_resolves_by_key_and_checksum_without_a_database():
    seeds = [{"key": SF5_KEY, "name": "Publish & prove", "description": "SF-5", "definition": sf5_v1()}]
    resolved = resolve_seed_fragments(b_source(), seeds)
    assert resolved[REF].version_id == "" and resolved[REF].checksum == sf5_checksum()
    assert compile_composite(b_source(), resolved).compiled_digest == BASE_DIGEST
    changed = copy.deepcopy(seeds)
    changed[0]["definition"]["nodes"][0]["label"] = "Reserve"
    try:
        resolve_seed_fragments(b_source(), changed)
    except ValueError as exc:
        assert [item["code"] for item in exc.errors] == ["fragment_pin_changed"]
    else:  # pragma: no cover
        raise AssertionError("a changed fragment never satisfies an old pin")


def test_golden_seed_file_compiles_b_from_its_source():
    """B's seed holds only ``definition_source``; it compiles to BASE_DIGEST with the shipped SF-5."""
    from tests.specification_engineering_graph_support import BASE_SEED_PATH

    entry = json.loads(BASE_SEED_PATH.read_text(encoding="utf-8"))  # B, kept only as the engineering graph's base
    assert entry["key"] == BASE_KEY and "definition" not in entry
    fragments = json.loads(Path(FRAGMENTS_SEED_PATH).read_text(encoding="utf-8"))
    assert next(item for item in fragments if item["key"] == SF5_KEY)["definition"] == sf5_v1()
    source = entry["definition_source"]
    composition = compile_composite(source, resolve_seed_fragments(source, fragments))
    assert composition.compiled_digest == BASE_DIGEST
