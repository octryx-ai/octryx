"""Workflow designer: where the boxes of a phased workflow are drawn is UI metadata in the draft, never execution."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.models import FlowDefinition
from app.models.runtime.flow_definition import FlowDefinitionVersion
from app.services.flow_definitions import validate_flow_definition
from app.services.workflow_runs.canvas_layout import clean_positions, layout_positions, with_layout
from app.services.workflow_runs.graph import parse_phased_definition
from tests.phased_workflow_fixtures import phased_definition, publish_phased

NODES = frozenset({"start", "work", "verify", "done"})


def test_positions_are_cleaned_never_refused():
    raw = {"work": {"x": 10.04, "y": -20}, "ghost": {"x": 1, "y": 1}, "done": {"x": "1", "y": 2},
           "verify": {"x": float("nan"), "y": 0}, "start": {"x": True, "y": 0}}
    assert clean_positions(raw, NODES) == {"work": {"x": 10.0, "y": -20.0}}
    assert clean_positions(["not", "a", "map"], NODES) == {}
    assert clean_positions({"work": {"x": 2e9, "y": 0}}, NODES) == {}
    assert layout_positions({"layout": "garbage"}, NODES) == {}
    assert "layout" not in with_layout({"layout": {"positions": {"work": {"x": 1, "y": 1}}}}, {})


def test_a_layout_block_changes_neither_validation_nor_the_graph_that_runs():
    plain = phased_definition()
    laid_out = with_layout(phased_definition(), {"work": {"x": 300.0, "y": 120.0}})
    broken = {**phased_definition(), "layout": {"positions": {"work": "left"}}}
    for definition in (laid_out, broken):
        assert validate_flow_definition(definition)["valid"] is True
        graph, reference = parse_phased_definition(definition), parse_phased_definition(plain)
        assert graph.nodes == reference.nodes
        assert graph.edges == reference.edges
        assert graph.order == reference.order


@pytest.mark.asyncio
async def test_the_layout_round_trips_through_a_draft_and_survives_a_phase_edit(client, auth_headers, db):
    key = await publish_phased(db, phased_definition())
    flow = (await db.execute(select(FlowDefinition).where(FlowDefinition.key == key))).scalar_one()
    published_id = flow.current_version_id
    url = f"/api/v1/phased-workflows/{flow.id}"

    view = (await client.get(url, headers=auth_headers)).json()
    assert view["layout"] == {"positions": {}}
    assert "config" in next(node for node in view["nodes"] if node["id"] == "work")

    moved = {"work": {"x": 320, "y": 140.25}, "ghost": {"x": 0, "y": 0}, "done": {"x": "far", "y": 0}}
    saved = await client.post(f"{url}/layout", headers=auth_headers,
                              json={"base_version_id": view["version_id"], "positions": moved})
    assert saved.status_code == 200, saved.text
    body = saved.json()
    assert body["version"] == view["version"] + 1
    assert body["version_status"] == "draft"
    assert body["published_version"] == view["version"]
    assert body["layout"] == {"positions": {"work": {"x": 320.0, "y": 140.2}}}

    # Never published: the workflow still runs the version it ran before.
    await db.refresh(flow)
    assert flow.current_version_id == published_id
    stored = await db.get(FlowDefinitionVersion, body["version_id"])
    assert stored.definition_json["layout"] == {"positions": {"work": {"x": 320.0, "y": 140.2}}}

    # The same positions again: no new version.
    same = (await client.post(f"{url}/layout", headers=auth_headers,
                              json={"base_version_id": body["version_id"], "positions": body["layout"]["positions"]}))
    assert same.json()["version"] == body["version"]

    stale = await client.post(f"{url}/layout", headers=auth_headers,
                              json={"base_version_id": view["version_id"], "positions": {}})
    assert stale.status_code == 409

    # A phase edit (Steps canvas) keeps where the boxes are drawn.
    phase = (await client.get(f"{url}/phases/work/graph", headers=auth_headers)).json()
    checks = [node for node in phase["graph"]["nodes"] if node["kind"] == "check"]
    edited = await client.post(f"{url}/phases/work/graph", headers=auth_headers,
                               json={"base_version_id": phase["version_id"], "graph": {"nodes": checks}})
    assert edited.status_code == 200, edited.text
    after = (await client.get(url, headers=auth_headers)).json()
    assert after["version"] == body["version"] + 1
    assert after["layout"] == body["layout"]

    # Auto-arrange: an empty layout removes the block.
    cleared = (await client.post(f"{url}/layout", headers=auth_headers,
                                 json={"base_version_id": after["version_id"], "positions": {}})).json()
    assert cleared["layout"] == {"positions": {}}
    assert "layout" not in (await db.get(FlowDefinitionVersion, cleared["version_id"])).definition_json


@pytest.mark.asyncio
async def test_moved_boxes_keep_a_shipped_seed_upgradable_and_move_along(db):
    from app.services.workflow_runs.seeding import definition_digest, phased_seeds, seed_phased_workflows
    from tests.phased_workflow_fixtures import admin_user

    seed = next(item for item in phased_seeds() if item["key"] == "bug-fix-reproduction")
    admin = await admin_user(db)
    flow = (await db.execute(select(FlowDefinition).where(FlowDefinition.key == seed["key"]))).scalar_one()
    current = await db.get(FlowDefinitionVersion, flow.current_version_id)
    earlier = {**seed["definition"], "plan_node": "fix"}  # the seed this installation was seeded with
    current.runtime_settings = {**dict(current.runtime_settings or {}), "seed_digest": definition_digest(earlier)}
    # The admin only moved two boxes of the shipped seed and published that.
    current.definition_json = with_layout(earlier, {"fix": {"x": 40.0, "y": 900.0}, "gone": {"x": 1.0, "y": 1.0}})
    await db.flush()

    assert (await seed_phased_workflows(db, admin_user=admin))["updated"] == 1
    await db.refresh(flow)
    upgraded = await db.get(FlowDefinitionVersion, flow.current_version_id)
    assert upgraded.status == "published"
    assert upgraded.definition_json["plan_node"] == seed["definition"]["plan_node"]
    assert upgraded.definition_json["layout"] == {"positions": {"fix": {"x": 40.0, "y": 900.0}}}


@pytest.mark.asyncio
async def test_a_seed_that_ships_its_own_layout_stays_upgradable_and_its_seed_draft_is_published(db):
    """team-delivery ships ``layout: {direction: tb}``; its seed digest and the stored version's digest must both
    include the layout, or the seeded version counts as admin-owned and a changed seed waits as a draft."""
    from app.services.workflow_runs.seeding import definition_digest, phased_seeds, seed_phased_workflows
    from tests.phased_workflow_fixtures import admin_user

    seed = next(item for item in phased_seeds() if item["key"] == "team-delivery")
    assert seed["definition"].get("layout", {}).get("direction") == "tb"
    admin = await admin_user(db)
    flow = (await db.execute(select(FlowDefinition).where(FlowDefinition.key == seed["key"]))).scalar_one()
    current = await db.get(FlowDefinitionVersion, flow.current_version_id)
    earlier = {**seed["definition"], "plan_node": "earlier"}  # the seeded version, with its layout
    current.definition_json = earlier
    current.runtime_settings = {**dict(current.runtime_settings or {}), "seed_digest": definition_digest(earlier)}
    # A changed seed is pending as a seed draft.
    db.add(FlowDefinitionVersion(flow_id=flow.id, version=99, status="draft", definition_json=earlier,
                                 validation_report={}, publish_metadata={}, policy_bindings={},
                                 runtime_settings={"seed": "phased_seed", "seed_digest": "sha256:old"},
                                 created_by=admin.id))
    await db.flush()

    assert (await seed_phased_workflows(db, admin_user=admin))["updated"] == 1
    await db.refresh(flow)
    upgraded = await db.get(FlowDefinitionVersion, flow.current_version_id)
    assert upgraded.status == "published" and upgraded.version == 99
    assert "plan_node" not in upgraded.definition_json or upgraded.definition_json.get("plan_node") != "earlier"


@pytest.mark.asyncio
async def test_changed_seeds_replace_the_seeded_versions_as_new_published_versions(db):
    """A changed team-delivery and spec-writing seed: each published version that was seeded (its ``seed_digest``)
    is replaced by the new seed as the next published version on the next start."""
    import copy

    from app.services.workflow_runs.seeding import definition_digest, phased_seeds, seed_phased_workflows
    from tests.phased_workflow_fixtures import admin_user

    seeds = {item["key"]: item for item in phased_seeds() if item["key"] in ("team-delivery", "spec-writing")}
    before = {}
    for key, seed in seeds.items():
        flow = (await db.execute(select(FlowDefinition).where(FlowDefinition.key == key))).scalar_one()
        current = await db.get(FlowDefinitionVersion, flow.current_version_id)
        earlier = copy.deepcopy(seed["definition"])
        for node in earlier["nodes"]:
            node.get("config", {}).pop("model_class", None)  # the seeded version: no phase model on interview / draft
        current.definition_json = earlier
        current.runtime_settings = {**dict(current.runtime_settings or {}), "seed_digest": definition_digest(earlier)}
        before[key] = (flow, current.version)
    await db.flush()

    assert (await seed_phased_workflows(db, admin_user=await admin_user(db)))["updated"] == 2
    for key, (flow, version) in before.items():
        await db.refresh(flow)
        upgraded = await db.get(FlowDefinitionVersion, flow.current_version_id)
        assert (upgraded.version, upgraded.status) == (version + 1, "published"), key
        assert upgraded.runtime_settings["seed_digest"] == definition_digest(seeds[key]["definition"])
    spec = await db.get(FlowDefinitionVersion, before["spec-writing"][0].current_version_id)
    assert next(node for node in spec.definition_json["nodes"] if node["id"] == "draft")["config"]["model_class"] == (
        "plan")
