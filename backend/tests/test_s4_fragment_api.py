"""S4.2: fragments and composites over the flow API (contract §2.2, §4).

A fragment is created by one admin and published by a second; a composite that references it by pin is stored
as its compiled graph with the complete composition block; ``POST /validate`` composes a source and returns the
composed report (and the compiled graph's errors); ``GET …/composition`` serves source, pins and provenance.
"""

from __future__ import annotations

import pytest

from tests.policy_engine_support import bearer
from tests.s4_fragment_support import (
    FLOWS,
    checksum,
    digest,
    make_admin,
    node_types,
    probe_composite,
    probe_fragment,
    unique_key,
)


async def _admins(db):
    author, reviewer = await make_admin(db), await make_admin(db)
    await db.commit()
    return author, reviewer


async def _fragment(client, author, reviewer) -> tuple[str, str, str, str]:
    key = unique_key("s4-probe-confirm")
    created = await client.post(FLOWS, headers=bearer(author.id),
                                json={"key": key, "name": "Probe confirm", "definition": probe_fragment()})
    assert created.status_code == 200, created.text
    version = created.json()["versions"][0]
    published = await client.post(f"{FLOWS}/versions/{version['id']}/publish", headers=bearer(reviewer.id))
    assert published.status_code == 200, published.text
    return key, created.json()["id"], version["id"], checksum(probe_fragment())


@pytest.mark.asyncio
async def test_a_fragment_is_created_and_published_by_a_second_admin(client, db):
    author, reviewer = await _admins(db)
    key = unique_key("s4-probe-confirm")
    created = await client.post(FLOWS, headers=bearer(author.id),
                                json={"key": key, "name": "Probe confirm", "definition": probe_fragment()})
    assert created.status_code == 200, created.text
    version = created.json()["versions"][0]
    assert version["definition"]["execution_kind"] == "phased_fragment"
    assert version["validation_report"]["valid"] is True

    own = await client.post(f"{FLOWS}/versions/{version['id']}/publish", headers=bearer(author.id))
    assert own.status_code == 409, own.text
    assert own.json()["detail"]["reason"] == "fragment_four_eyes"

    published = await client.post(f"{FLOWS}/versions/{version['id']}/publish", headers=bearer(reviewer.id))
    assert published.status_code == 200, published.text
    row = next(item for item in published.json()["versions"] if item["id"] == version["id"])
    assert row["status"] == "published" and row["published_by"] == reviewer.id
    metadata = row["publish_metadata"]
    assert metadata["capability_enabled"] is False and metadata["llm_visible"] is False
    assert metadata["approval_mode"] == "four_eyes"


@pytest.mark.asyncio
async def test_a_composite_is_stored_as_its_compiled_graph_with_a_complete_composition(client, db):
    author, reviewer = await _admins(db)
    key, _flow_id, fragment_version_id, pin = await _fragment(client, author, reviewer)
    source = probe_composite(key, fragment_version_id, pin)

    created = await client.post(FLOWS, headers=bearer(author.id),
                                json={"key": unique_key("s4-probe"), "name": "Probe", "definition": source})
    assert created.status_code == 200, created.text
    version = created.json()["versions"][0]
    definition = version["definition"]
    assert "fragment" not in node_types(definition)
    assert [node["id"] for node in definition["nodes"]] == ["start", "probe.confirm", "done", "blocked", "stopped"]
    assert {(edge["source_node_id"], edge["target_node_id"]) for edge in definition["edges"]} == {
        ("start", "probe.confirm"), ("probe.confirm", "done"), ("probe.confirm", "blocked"),
        ("probe.confirm", "stopped")}

    composition = version["runtime_settings"]["composition"]
    assert composition["source"] == source
    assert composition["source_hash"] == checksum(source)
    assert composition["compiled_digest"] == digest(definition)
    [fragment] = composition["fragments"]
    assert {name: fragment[name] for name in ("ref", "key", "version", "version_id", "checksum", "namespace")} == {
        "ref": "probe", "key": key, "version": 1, "version_id": fragment_version_id, "checksum": pin,
        "namespace": "probe."}
    assert set(composition["provenance"]) == {"probe.confirm"}
    assert composition["provenance"]["probe.confirm"]["node"] == "confirm"
    assert composition["provenance"]["probe.confirm"]["version_id"] == fragment_version_id
    assert version["validation_report"]["valid"] is True
    assert version["validation_report"]["composition"]["compiled_digest"] == digest(definition)

    # D2b2 (replaces D-S4-4's author publish): a composite is a phased workflow, so a second admin publishes it.
    own = await client.post(f"{FLOWS}/versions/{version['id']}/publish", headers=bearer(author.id))
    assert own.status_code == 409 and own.json()["detail"]["reason"] == "workflow_four_eyes"
    published = await client.post(f"{FLOWS}/versions/{version['id']}/publish", headers=bearer(reviewer.id))
    assert published.status_code == 200, published.text
    row = next(item for item in published.json()["versions"] if item["id"] == version["id"])
    assert row["status"] == "published" and row["definition"] == definition


@pytest.mark.asyncio
async def test_validate_composes_a_source_and_returns_the_compiled_graphs_errors(client, db):
    author, reviewer = await _admins(db)
    key, _flow_id, fragment_version_id, pin = await _fragment(client, author, reviewer)

    valid = await client.post(f"{FLOWS}/validate", headers=bearer(author.id),
                              json={"definition": probe_composite(key, fragment_version_id, pin)})
    assert valid.status_code == 200, valid.text
    assert valid.json()["valid"] is True
    assert valid.json()["composition"]["fragments"][0]["key"] == key
    assert valid.json()["composition"]["compiled_digest"].startswith("sha256:")

    unmapped = await client.post(f"{FLOWS}/validate", headers=bearer(author.id), json={
        "definition": probe_composite(key, fragment_version_id, pin, ports={"go": "done", "back": "blocked"})})
    assert unmapped.status_code == 422, unmapped.text
    assert "fragment_port_unmapped" in {item["code"] for item in unmapped.json()["detail"]["errors"]}

    # A ``next`` port back to the start: the compiled graph has a cycle without a loop edge, judged by the
    # unchanged phased validator.
    cycle = await client.post(f"{FLOWS}/validate", headers=bearer(author.id), json={
        "definition": probe_composite(key, fragment_version_id, pin,
                                      ports={"go": "start", "back": "blocked", "stop": "stopped"})})
    assert cycle.status_code == 422, cycle.text
    assert "cycle_without_loop_edge" in {item["code"] for item in cycle.json()["detail"]["errors"]}

    # A fragment is validated as a fragment: an outcome inside is refused.
    bad = probe_fragment()
    bad["nodes"].append({"id": "end", "type": "outcome", "config": {"outcome": "done"}})
    fragment_report = await client.post(f"{FLOWS}/validate", headers=bearer(author.id), json={"definition": bad})
    assert fragment_report.status_code == 200, fragment_report.text
    assert fragment_report.json()["valid"] is False
    assert "fragment_node_kind" in {item["code"] for item in fragment_report.json()["errors"]}


@pytest.mark.asyncio
async def test_the_composition_of_a_version_is_served_read_only(client, db):
    author, reviewer = await _admins(db)
    key, fragment_flow_id, fragment_version_id, pin = await _fragment(client, author, reviewer)
    source = probe_composite(key, fragment_version_id, pin)
    created = (await client.post(FLOWS, headers=bearer(author.id),
                                 json={"key": unique_key("s4-probe"), "name": "Probe", "definition": source})).json()
    flow_id, version_id = created["id"], created["versions"][0]["id"]

    served = await client.get(f"{FLOWS}/{flow_id}/versions/{version_id}/composition", headers=bearer(reviewer.id))
    assert served.status_code == 200, served.text
    body = served.json()
    assert set(body) == {"source", "fragments", "provenance", "compiled_digest"}
    assert body["source"] == source
    assert body["fragments"][0]["version_id"] == fragment_version_id and body["fragments"][0]["checksum"] == pin
    assert body["provenance"]["probe.confirm"]["key"] == key
    assert body["compiled_digest"] == digest(created["versions"][0]["definition"])

    plain = await client.get(f"{FLOWS}/{fragment_flow_id}/versions/{fragment_version_id}/composition",
                             headers=bearer(reviewer.id))
    assert plain.status_code == 404 and plain.json()["detail"]["reason"] == "composition_not_found"
    elsewhere = await client.get(f"{FLOWS}/{fragment_flow_id}/versions/{version_id}/composition",
                                 headers=bearer(reviewer.id))
    assert elsewhere.status_code == 404 and elsewhere.json()["detail"]["reason"] == "flow_version_not_found"
