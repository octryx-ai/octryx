"""Workflow designer D2b1: a hand-drawn draft is saved even while it is incomplete (with its report), never published or
run while invalid; validation names the box or arrow; the side panel's catalog; hand-made groups are display only."""

from __future__ import annotations

import copy

import pytest
from sqlalchemy import select

from app.models import FlowDefinition, User
from app.models.runtime.flow_definition import FlowDefinitionVersion
from app.services.auth import create_access_token
from app.services.flow_definitions import create_flow_definition, validate_flow_definition
from app.services.workflow_runs.canvas_layout import clean_groups, layout_groups, with_clean_layout, with_layout
from app.services.workflow_runs.engine import start_phased_run
from app.services.workflow_runs.graph import GATE_CHECK_TYPES, parse_phased_definition
from app.services.workflow_runs.records import WorkflowRunError
from tests.phased_workflow_fixtures import admin_user, phased_definition, publish_phased
from tests.policy_engine_support import bearer
from tests.s4_fragment_support import make_admin

NODES = frozenset({"start", "work", "verify", "done"})


def _incomplete() -> dict:
    definition = phased_definition()
    definition["nodes"][2]["config"] = {"checks": []}
    definition["edges"] = [edge for edge in definition["edges"] if edge["id"] != "e2"]
    return definition


@pytest.mark.asyncio
async def test_new_workflow_starts_as_a_draft_with_start_and_end(client, auth_headers, db):
    created = await client.post("/api/v1/phased-workflows", headers=auth_headers, json={"title": "Release notes"})
    assert created.status_code == 200, created.text
    view = created.json()
    assert (view["title"], view["version"], view["version_status"], view["published_version"]) == (
        "Release notes", 1, "draft", None)
    assert [(node["id"], node["kind"]) for node in view["nodes"]] == [("start", "start"), ("end", "outcome")]
    assert view["validation_report"]["valid"] is True
    assert view["definition"]["execution_kind"] == "phased"
    assert view["composite"] is False
    assert view["review_state"] is None
    flow = await db.get(FlowDefinition, view["flow_id"])
    assert flow.status == "draft" and flow.key.startswith("release-notes-")


@pytest.mark.asyncio
async def test_an_invalid_draft_is_saved_with_its_report_but_never_published_or_run(client, auth_headers, db):
    key = await publish_phased(db, phased_definition())
    flow = (await db.execute(select(FlowDefinition).where(FlowDefinition.key == key))).scalar_one()
    published_id = flow.current_version_id
    url = f"/api/v1/phased-workflows/{flow.id}"
    view = (await client.get(url, headers=auth_headers)).json()

    saved = await client.post(f"{url}/definition", headers=auth_headers, json={
        "base_version_id": view["version_id"], "definition": _incomplete(), "title": "Evidence run, reworked"})
    assert saved.status_code == 200, saved.text
    body = saved.json()
    assert (body["version"], body["version_status"], body["title"]) == (view["version"] + 1, "draft",
                                                                        "Evidence run, reworked")
    assert body["validation_report"]["valid"] is False
    stored = await db.get(FlowDefinitionVersion, body["version_id"])
    assert stored.validation_report["valid"] is False
    assert body["can_publish"] is False and "second admin" in body["publish_reason"]
    codes = {error["code"] for error in stored.validation_report["errors"]}
    assert {"gate_without_checks", "dead_end"} <= codes
    await db.refresh(flow)
    assert flow.current_version_id == published_id

    own = await client.post(f"/api/v1/flows/versions/{body['version_id']}/publish", headers=auth_headers)
    assert own.status_code == 409 and own.json()["detail"]["reason"] == "workflow_four_eyes"
    reviewer = await make_admin(db)
    await db.commit()
    refused = await client.post(f"/api/v1/flows/versions/{body['version_id']}/publish", headers=bearer(reviewer.id))
    assert refused.status_code == 422
    assert refused.json()["detail"]["valid"] is False
    as_reviewer = (await client.get(url, headers=bearer(reviewer.id))).json()
    assert as_reviewer["can_publish"] is True and as_reviewer["publish_reason"] == ""
    await db.refresh(stored)
    assert stored.status == "draft"

    with pytest.raises(WorkflowRunError) as raised:
        await start_phased_run(db, user=await admin_user(db), flow=flow, version=stored, project_id=None, item=None,
                               repository=None, branch=None, session=None)
    assert raised.value.code == "invalid_phased_workflow"

    stale = await client.post(f"{url}/definition", headers=auth_headers, json={
        "base_version_id": view["version_id"], "definition": phased_definition()})
    assert stale.status_code == 409
    missing = await client.post(f"{url}/definition", headers=auth_headers, json={"base_version_id": body["version_id"]})
    assert missing.status_code == 422


@pytest.mark.asyncio
async def test_an_invalid_phased_workflow_is_created_but_a_flow_graph_or_a_secret_is_still_refused(db):
    admin = await admin_user(db)
    created = await create_flow_definition(db, current_user=admin, payload={
        "key": "designer-incomplete", "name": "Incomplete", "definition": _incomplete()})
    assert created["versions"][0]["validation_report"]["valid"] is False

    from fastapi import HTTPException

    with pytest.raises(HTTPException) as graph:
        await create_flow_definition(db, current_user=admin, payload={
            "key": "designer-flow-graph", "name": "Flow graph", "definition": {"nodes": [], "edges": []}})
    assert graph.value.status_code == 422
    secret = _incomplete()
    secret["nodes"][1]["config"]["api_key"] = "never-persist-this"
    with pytest.raises(HTTPException) as leaked:
        await create_flow_definition(db, current_user=admin, payload={
            "key": "designer-secret", "name": "Secret", "definition": secret})
    assert leaked.value.status_code == 422




def test_validation_names_the_box_or_arrow_in_plain_words():
    definition = _incomplete()
    definition["edges"].append({"id": "bad-loop", "source_node_id": "work", "target_node_id": "done", "kind": "loop"})
    errors = validate_flow_definition(definition)["errors"]
    by_code = {error["code"]: error for error in errors}
    assert by_code["gate_without_checks"]["node_id"] == "verify"
    assert by_code["gate_without_checks"]["message"] == "“Evidence read” needs at least one check."
    assert by_code["unbounded_loop"]["edge_id"] == "bad-loop" and by_code["unbounded_loop"]["node_id"] == "work"
    assert by_code["loop_not_back_edge"]["edge_id"] == "bad-loop"
    assert "“Collect evidence”" in by_code["unbounded_loop"]["message"]
    assert all("node_id" in error or "edge_id" in error for error in errors)
    assert not any("'" in error["message"] for error in errors if error["code"] in by_code)


@pytest.mark.asyncio
async def test_the_catalog_lists_what_the_side_panel_offers_to_admins_only(client, auth_headers, db):
    await publish_phased(db, phased_definition(), key="designer-child")
    response = await client.get("/api/v1/phased-workflows/catalog", headers=auth_headers)
    assert response.status_code == 200, response.text
    catalog = response.json()
    assert set(catalog) == {"agents", "tools", "checkTypes", "gateCheckTypes", "workflows", "platformActions",
                            "confirmationSubjects", "watchConditions", "outcomes", "deciders", "workItemFields",
                            "parallelWork"}
    assert all({"key", "label", "kind"} <= set(field) for field in catalog["workItemFields"])
    assert catalog["parallelWork"]["routes"] == ["done", "replan"]
    assert catalog["parallelWork"]["planTool"] == "submit_work_plan"
    assert catalog["workItemFields"]
    assert {agent["key"] for agent in catalog["agents"]} == {"assistant", "engineer"}
    assert all(agent["capability_ceiling"] in {"read_only", "change", "deliver"} for agent in catalog["agents"])
    assert "knowledge_search" in catalog["tools"] and catalog["tools"] == sorted(catalog["tools"])
    tool_called = next(item for item in catalog["checkTypes"] if item["type"] == "tool_called")
    assert tool_called == {"type": "tool_called", "label": "A tool was called", "params": ["tools"]}
    assert set(catalog["gateCheckTypes"]) == set(GATE_CHECK_TYPES)
    assert {"key": "designer-child", "title": "Evidence run"} in catalog["workflows"]
    ci = next(item for item in catalog["platformActions"] if item["key"] == "ci.status")
    assert ci["routes"] == ["failed", "running", "succeeded"] and ci["label"] == "Read the CI status"
    push = next(item for item in catalog["platformActions"] if item["key"] == "scm.push")
    assert push["routes"] == ["failed", "succeeded"]
    assert "advance" in catalog["confirmationSubjects"] and "ci.failed" in catalog["watchConditions"]
    assert "done" in catalog["outcomes"]
    assert catalog["deciders"][:4] == ["requester", "item_owner", "handoff_owner", "spec_origin"]
    assert any(value.startswith("role:") for value in catalog["deciders"])

    assert (await client.get("/api/v1/phased-workflows/catalog")).status_code == 401
    user = User(username="designer-reader", email="designer-reader@example.test", password_hash="!", is_active=True)
    db.add(user)
    await db.commit()
    token = create_access_token(user.id)
    other = await client.get("/api/v1/phased-workflows/catalog", headers={"Authorization": f"Bearer {token}"})
    assert other.status_code == 403


def test_groups_are_cleaned_like_positions():
    raw = [
        {"id": "g1", "label": "  Evidence  ", "members": ["work", "ghost", "verify", "work"]},
        {"id": "g2", "label": 7, "members": ["verify", "done"]},
        {"id": "g1", "label": "duplicate id", "members": ["start"]},
        {"id": "", "members": ["start"]},
        {"id": "g3", "members": ["ghost"]},
        "not a group",
    ]
    assert clean_groups(raw, NODES) == [
        {"id": "g1", "label": "Evidence", "members": ["work", "verify"]},
        {"id": "g2", "label": "", "members": ["done"]},
    ]
    assert clean_groups(None, NODES) is None
    assert clean_groups([], NODES) == []
    assert layout_groups({"layout": {"groups": "garbage"}}, NODES) is None


def test_groups_never_change_validation_or_the_graph_that_runs_and_survive_a_layout_save():
    plain = phased_definition()
    grouped = with_layout(phased_definition(), {"work": {"x": 1.0, "y": 2.0}},
                          [{"id": "g1", "label": "Evidence", "members": ["work", "verify"]}])
    assert validate_flow_definition(grouped)["valid"] is True
    graph, reference = parse_phased_definition(grouped), parse_phased_definition(plain)
    assert (graph.nodes, graph.edges, graph.order) == (reference.nodes, reference.edges, reference.order)
    assert with_layout(grouped, {})["layout"] == {"groups": [{"id": "g1", "label": "Evidence",
                                                               "members": ["work", "verify"]}]}
    dirty = copy.deepcopy(grouped)
    dirty["layout"]["groups"].append({"id": "g2", "members": ["ghost"]})
    dirty["layout"]["positions"]["ghost"] = {"x": 1, "y": 1}
    dirty["layout"]["direction"] = "lr"
    dirty["layout"]["zoom"] = 3
    cleaned = with_clean_layout(dirty, NODES)
    assert cleaned["layout"] == {"positions": {"work": {"x": 1.0, "y": 2.0}}, "direction": "lr",
                                 "groups": [{"id": "g1", "label": "Evidence", "members": ["work", "verify"]}]}
    assert "direction" not in with_clean_layout({**dirty, "layout": {**dirty["layout"], "direction": "up"}},
                                                NODES)["layout"]
    assert "layout" not in with_clean_layout({**plain, "layout": "broken"}, NODES)


@pytest.mark.asyncio
async def test_saved_groups_come_back_cleaned_in_the_view(client, auth_headers, db):
    key = await publish_phased(db, phased_definition())
    flow = (await db.execute(select(FlowDefinition).where(FlowDefinition.key == key))).scalar_one()
    url = f"/api/v1/phased-workflows/{flow.id}"
    view = (await client.get(url, headers=auth_headers)).json()
    assert "groups" not in view["layout"]
    definition = copy.deepcopy(view["definition"])
    definition["layout"] = {"groups": [{"id": "g1", "label": "Evidence", "members": ["work", "verify", "ghost"]}]}
    saved = (await client.post(f"{url}/definition", headers=auth_headers, json={
        "base_version_id": view["version_id"], "definition": definition})).json()
    assert saved["layout"] == {"positions": {}, "groups": [{"id": "g1", "label": "Evidence",
                                                            "members": ["work", "verify"]}]}
    assert saved["validation_report"]["valid"] is True
    moved = (await client.post(f"{url}/layout", headers=auth_headers, json={
        "base_version_id": saved["version_id"], "positions": {"work": {"x": 5, "y": 5}}})).json()
    assert moved["layout"]["groups"] == saved["layout"]["groups"]
    requested = await client.post(f"/api/v1/flows/versions/{moved['version_id']}/request-review", headers=auth_headers)
    assert requested.status_code == 200, requested.text
    assert (await client.get(url, headers=auth_headers)).json()["review_state"] == "awaiting_approval"


def test_acceptance_fixtures_are_test_flows_hidden_from_the_list():
    from app.services.workflow_runs.overview_flows import is_test_flow

    assert is_test_flow(FlowDefinitionVersion(publish_metadata={"test_fixture": True})) is True
    assert is_test_flow(FlowDefinitionVersion(publish_metadata={})) is False


@pytest.mark.asyncio
async def test_a_workflow_built_from_fragments_becomes_editable_through_a_detached_draft(client, auth_headers, db):
    from tests.s4_fragment_support import create, probe_composite, publish, published_fragment, unique_key

    author, reviewer = await make_admin(db), await make_admin(db)
    key, _, fragment_version_id, sha = await published_fragment(db, author, reviewer)
    composite_key = unique_key("detach")
    created = await create(db, author, composite_key, probe_composite(key, fragment_version_id, sha))
    await publish(db, created["versions"][0]["id"], reviewer)
    await db.commit()
    url = f"/api/v1/phased-workflows/{created['id']}"
    view = (await client.get(url, headers=auth_headers)).json()
    assert view["composite"] is True

    refused = await client.post(f"{url}/definition", headers=auth_headers, json={
        "base_version_id": view["version_id"], "definition": view["definition"]})
    assert refused.status_code == 409 and refused.json()["detail"]["code"] == "composite_structure"

    detached = await client.post(f"{url}/definition", headers=auth_headers, json={
        "base_version_id": view["version_id"], "definition": view["definition"], "detach": True})
    assert detached.status_code == 200, detached.text
    draft = detached.json()
    assert (draft["version_status"], draft["composite"]) == ("draft", False)
    assert {node["id"] for node in draft["nodes"]} == {node["id"] for node in view["nodes"]}

    extended = copy.deepcopy(draft["definition"])
    extended["nodes"].append({"id": "extra", "type": "outcome", "label": "Extra", "config": {"outcome": "done"}})
    saved = await client.post(f"{url}/definition", headers=auth_headers, json={
        "base_version_id": draft["version_id"], "definition": extended})
    assert saved.status_code == 200, saved.text
    assert "extra" in {node["id"] for node in saved.json()["nodes"]}
    flow = await db.get(FlowDefinition, created["id"])
    await db.refresh(flow)
    assert flow.current_version_id == created["versions"][0]["id"]
