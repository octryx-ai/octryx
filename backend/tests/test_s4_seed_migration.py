"""Compiling the shipped SF-5 fragment preserves B's graph, its digest and the engineering B derived from it.

The test derives, from the shipped B seed, exactly the two seed forms the seeder ships:

- ``sf5_fragment(b)``: the fragment ``sf-publish-prove`` v1, the 6 SF-5 nodes and their 14 edges verbatim, its four
  exits as ports;
- ``b_source(b, checksum)``: B's ``definition_source``, the 6 nodes replaced by one ``publish_prove`` reference at node
  index 23 and the 14 edges by one ``{"fragment_edges": "publish_prove"}`` marker at edge index 56.

Compiling the source with the fragment must give B back list-for-list, so its digest stays ``BASE_DIGEST`` and the
accepted-spec engineering graph derived from it is unchanged. The compiler is ``compile_composite``.
"""

from __future__ import annotations

import copy
import json
from typing import Any

import pytest
from sqlalchemy import delete, select

from app.models import FlowDefinition
from app.models.runtime.flow_definition import FlowDefinitionVersion
from app.services.workflow_runs import seeding
from app.services.workflow_runs.fragments.compiler import compile_composite
from app.services.workflow_runs.fragments.format import ResolvedFragment, parse_fragment
from app.services.workflow_runs.handoff.contract import canonical_hash
from app.services.workflow_runs.seeding import definition_digest, phased_seeds, seed_phased_workflows
from tests.phased_workflow_fixtures import admin_user
from tests.specification_engineering_graph_support import (
    BASE_DIGEST,
    BASE_KEY,
    BASE_SEED_PATH,
    SPEC_ORIGIN_NODES,
    base_seed,
    spec_engineering_definition,
)

SF5_KEY = "sf-publish-prove"
SF5_REF = "publish_prove"
SF5_NODES = ("reserve_publication", "confirm_publication", "publish_docs", "docs_in_knowledge", "audience_proof",
             "outsider_proof")
SF5_NODE_INDEX, SF5_EDGE_INDEX = 23, 56
SF5_PORTS = {"proven": {"edge": "next", "accepts": "any"}, "failed": {"edge": "next", "accepts": "pause"},
             "stopped": {"edge": "next", "accepts": "outcome"}, "rework": {"edge": "loop", "accepts": "any"}}
B_PORT_TARGETS = {"proven": "acceptance_open", "failed": "action_failed", "stopped": "stopped",
                  "rework": "doc_final"}
SF5_EDGE_COUNT = 14
SF5_V1_CHECKSUM = "sha256:e9165bc6bf990bce5033a52d9061323c1b4a0319c899c5bb2fcc3290a1b27248"
FRAGMENT_SEED_MARKER = "phased_fragments"


# --- the migration harness (it writes the seed snippets) ------------------------------------------------------------


def _b_seed() -> dict[str, Any]:
    return base_seed()


def _sf5_block(b: dict[str, Any]) -> tuple[list[dict], list[dict]]:
    """SF-5's 6 nodes and 14 edges; both contiguous at the contract's indices, else the harness refuses."""
    ids = [node["id"] for node in b["nodes"]]
    assert ids[SF5_NODE_INDEX:SF5_NODE_INDEX + len(SF5_NODES)] == list(SF5_NODES), "SF-5 nodes moved in B"
    edges = b["edges"][SF5_EDGE_INDEX:SF5_EDGE_INDEX + SF5_EDGE_COUNT]
    assert all(edge["source_node_id"] in SF5_NODES for edge in edges), "SF-5 edges moved in B"
    assert sum(edge["source_node_id"] in SF5_NODES for edge in b["edges"]) == SF5_EDGE_COUNT
    return copy.deepcopy(b["nodes"][SF5_NODE_INDEX:SF5_NODE_INDEX + len(SF5_NODES)]), copy.deepcopy(edges)


def sf5_fragment(b: dict[str, Any]) -> dict[str, Any]:
    """``sf-publish-prove`` v1: an exit edge names its port instead of its target."""
    nodes, edges = _sf5_block(b)
    port_of = {target: port for port, target in B_PORT_TARGETS.items()}
    for edge in edges:
        if edge["target_node_id"] not in SF5_NODES:
            port = port_of[edge.pop("target_node_id")]
            assert edge.get("kind", "next") == SF5_PORTS[port]["edge"]
            edge["target_port"] = port
    return {
        "execution_kind": "phased_fragment",
        "schema_version": "fragment/v1",
        "entry": SF5_NODES[0],
        "ports": copy.deepcopy(SF5_PORTS),
        "requires": ["feature_documentation"],
        "provides": [],
        "instance": "single",
        "nodes": nodes,
        "edges": edges,
    }


def b_source(b: dict[str, Any], checksum: str) -> dict[str, Any]:
    """B's ``definition_source``: the seed path pins by checksum only (no version id)."""
    _sf5_block(b)
    source = copy.deepcopy(b)
    reference = {"id": SF5_REF, "type": "fragment", "label": "Publish & prove",
                 "config": {"fragment_key": SF5_KEY, "fragment_checksum": checksum, "namespace": "",
                            "ports": dict(B_PORT_TARGETS)}}
    source["nodes"][SF5_NODE_INDEX:SF5_NODE_INDEX + len(SF5_NODES)] = [reference]
    source["edges"][SF5_EDGE_INDEX:SF5_EDGE_INDEX + SF5_EDGE_COUNT] = [{"fragment_edges": SF5_REF}]
    for edge in source["edges"]:
        if edge.get("target_node_id") == SF5_NODES[0]:
            edge["target_node_id"] = SF5_REF
    return source


def compile_b(source: dict[str, Any], fragment: dict[str, Any]) -> tuple[dict, dict]:
    checksum = canonical_hash(fragment)
    resolved = ResolvedFragment(key=SF5_KEY, version_id="", version=1, checksum=checksum,
                                definition=parse_fragment(fragment))
    composition = compile_composite(source, {SF5_REF: resolved})
    return composition.definition, composition.provenance


def migrated_forms() -> tuple[dict[str, Any], dict[str, Any], str]:
    """``(fragment, b_source, checksum)`` from the shipped B (compiled again once B is a ``definition_source``)."""
    b = _b_seed()["definition"]
    fragment = sf5_fragment(b)
    checksum = canonical_hash(fragment)
    return fragment, b_source(b, checksum), checksum


# --- the tests ----------------------------------------------------------------------------------------------------


def test_the_b_seed_digest_is_the_engineering_base_digest_golden():
    """The golden digest test: B ships as its composite source only, compiled it is ``BASE_DIGEST``, and the
    shipped forms are exactly the harness forms."""
    seed = _b_seed()
    assert definition_digest(seed["definition"]) == BASE_DIGEST
    # B is not shipped as a workflow; its source stays as the engineering graph's base (``BASE_SEED_PATH``).
    raw = json.loads(BASE_SEED_PATH.read_text(encoding="utf-8"))
    assert raw["key"] == BASE_KEY
    assert "definition_source" in raw and "definition" not in raw
    fragment, source, checksum = migrated_forms()
    assert seed["definition_source"] == source
    fragment_seed = next(item for item in seeding.phased_fragment_seeds() if item["key"] == SF5_KEY)
    assert fragment_seed["definition"] == fragment and canonical_hash(fragment_seed["definition"]) == checksum
    assert checksum == SF5_V1_CHECKSUM


def test_the_b_source_compiles_back_to_b_list_for_list():
    b = _b_seed()["definition"]
    fragment, source, checksum = migrated_forms()
    assert (len(source["nodes"]), len(source["edges"])) == (41, 73)
    assert source["nodes"][SF5_NODE_INDEX]["id"] == SF5_REF
    assert source["edges"][SF5_EDGE_INDEX] == {"fragment_edges": SF5_REF}
    assert not any(node["id"] in SF5_NODES for node in source["nodes"])
    assert [edge["id"] for edge in source["edges"] if edge.get("target_node_id") == SF5_REF] == [
        "e-accepted", "e-not-testable"]
    assert sorted(edge["target_port"] for edge in fragment["edges"] if "target_port" in edge) == [
        "failed", "failed", "failed", "failed", "failed", "proven", "rework", "stopped"]
    assert len(checksum) == 71

    compiled, provenance = compile_b(source, fragment)
    assert compiled == b  # deep equality: node and edge order included
    assert definition_digest(compiled) == BASE_DIGEST
    assert sorted(provenance) == sorted(SF5_NODES)
    assert {item["key"] for item in provenance.values()} == {SF5_KEY}
    assert {item["checksum"] for item in provenance.values()} == {checksum}
    assert definition_digest(source) != BASE_DIGEST  # the digest is over the compiled graph, never the source


def test_the_harness_refuses_a_b_whose_sf5_block_moved():
    b = copy.deepcopy(_b_seed()["definition"])
    b["nodes"].insert(SF5_NODE_INDEX, b["nodes"].pop(SF5_NODE_INDEX + 2))
    with pytest.raises(AssertionError, match="SF-5 nodes moved"):
        sf5_fragment(b)


@pytest.mark.asyncio
async def test_a_second_boot_reports_everything_unchanged(db):
    admin = await admin_user(db)
    await seed_phased_workflows(db, admin_user=admin)
    counts = await seed_phased_workflows(db, admin_user=admin)
    assert (counts["created"], counts["updated"], counts["unchanged"]) == (0, 0, len(phased_seeds()))
    assert counts["fragments"] == {"created": 0, "updated": 0, "unchanged": 0}  # no shipped workflow uses SF-5


def test_the_spec_engineering_graph_is_still_built_from_the_same_base():
    definition = spec_engineering_definition()  # raises when the base seed's B is not BASE_DIGEST
    nodes = {node["id"]: node for node in definition["nodes"]}
    assert len(definition["nodes"]) == len(_b_seed()["definition"]["nodes"]) == 46
    assert len(definition["edges"]) == 86
    assert all(nodes[node_id]["config"]["decider"] == "spec_origin" for node_id in SPEC_ORIGIN_NODES)
    assert not any(node.get("type") == "fragment" for node in definition["nodes"])  # never a source form
    assert set(SF5_NODES) <= set(nodes)


@pytest.mark.asyncio
async def test_the_seeder_never_creates_b_or_its_fragment(db):
    """feature-delivery-tdd (B) is not shipped as a workflow, so the seeder never creates it, nor SF-5, which only B
    uses (a fresh installation would list a part no workflow of it runs)."""
    admin = await admin_user(db)
    flows = (await db.execute(select(FlowDefinition.id).where(
        FlowDefinition.key.in_((BASE_KEY, SF5_KEY)), FlowDefinition.project_id.is_(None)))).scalars().all()
    await db.execute(delete(FlowDefinitionVersion).where(FlowDefinitionVersion.flow_id.in_(flows)))
    await db.execute(delete(FlowDefinition).where(FlowDefinition.id.in_(flows)))
    await db.flush()

    counts = await seed_phased_workflows(db, admin_user=admin)

    assert counts["created"] == 0 and counts["fragments"]["created"] == 0
    assert (await db.execute(select(FlowDefinition).where(
        FlowDefinition.key.in_((BASE_KEY, SF5_KEY)), FlowDefinition.project_id.is_(None)))).scalars().first() is None
