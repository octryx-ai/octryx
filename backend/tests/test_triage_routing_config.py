"""The route by type resolves from defaults, the Workspace setting and the triage definition's validated routing block, incidents skip the triage, the run start preselects the entry workflow, and the Workspace routes are read and replaced through the API."""

from __future__ import annotations

import pytest
from sqlalchemy import func, select

from app.models import Project, WorkflowRun
from app.models.runtime.secure_work import WorkItem
from app.services.workflow_runs.graph import PhasedNode
from app.services.workflow_runs.graph_validation import validate_phased_definition
from app.services.workflow_runs.triage_routing import (
    DEFAULT_ROUTES,
    ROUTING_KEY,
    RoutingSettingsError,
    effective_routes,
    entry_workflow_for,
    normalize_settings,
    routes_for_run,
    workspace_routes,
)
from tests.knowledge_evidence_seed_support import seed_workspace
from tests.triage_routing_support import _item, _server_pipeline, _triage_seed  # noqa: F401

# ---- the mapping --------------------------------------------------------------------------------------------------

def test_defaults_then_workspace_then_definition_each_replacing_single_types():
    assert DEFAULT_ROUTES == {"feature": "epic-delivery", "bug": "bug-fix-reproduction",
                              "incident": "incident-analysis"}
    workspace = normalize_settings({"routes": {"Bug": "review-and-pr", "security": "incident-analysis",
                                               "incident": None}})["routes"]
    assert workspace == {"bug": "review-and-pr", "security": "incident-analysis", "incident": None}
    routes = effective_routes(workspace, {"bug": "bug-fix-reproduction"})
    assert routes == {"feature": "epic-delivery", "bug": "bug-fix-reproduction", "incident": None,
                      "security": "incident-analysis"}
    assert workspace_routes({"triage_routing": {"routes": {"bad type": "x"}}}) == ({}, "invalid")
    for value, code in (({"routes": {"feature": "jira-intake-triage"}}, "route_to_triage"),
                        ({"routes": {"bad type": "x"}}, "type_invalid"),
                        ({"routes": {"feature": 3}}, "workflow_key_invalid"),
                        ({"routes": {}, "extra": 1}, "unknown_key")):
        with pytest.raises(RoutingSettingsError) as refused:
            normalize_settings(value)
        assert refused.value.code == code


def test_a_triage_outcome_routing_block_is_validated_with_the_definition():
    definition = _triage_seed()
    ready = next(node for node in definition["nodes"] if node["id"] == "ready")
    ready["config"][ROUTING_KEY] = {"routes": {"feature": "incident-analysis", "task": None}}
    assert validate_phased_definition(definition)["valid"]
    ready["config"][ROUTING_KEY] = {"routes": {"feature": "jira-intake-triage"}}
    codes = [error["code"] for error in validate_phased_definition(definition)["errors"]]
    assert codes == ["outcome_routing"]


@pytest.mark.asyncio
async def test_the_definition_block_overrides_the_workspace_setting(db):
    workspace_id = await seed_workspace(db)
    project = await db.get(Project, workspace_id)
    project.config = {"triage_routing": {"routes": {"feature": "review-and-pr", "bug": None}}}
    run = WorkflowRun(project_id=workspace_id, workflow_key="jira-intake-triage")
    plain = PhasedNode(id="ready", kind="outcome", title="Ready", config={"outcome": "done"})
    assert (await routes_for_run(db, run, plain))["feature"] == "review-and-pr"
    node = PhasedNode(id="ready", kind="outcome", title="Ready",
                      config={"outcome": "done", ROUTING_KEY: {"routes": {"feature": "incident-analysis"}}})
    routes = await routes_for_run(db, run, node)
    assert (routes["feature"], routes["bug"], routes["incident"]) == ("incident-analysis", None, "incident-analysis")


# ---- the entry workflow -------------------------------------------------------------------------------------------

def test_incidents_skip_the_triage_everything_else_is_triaged_first():
    def item(source: str, kind: str | None) -> WorkItem:
        return WorkItem(source_type=source, issue_type=kind, source_key="X-1", title="x")

    assert entry_workflow_for(item("jira", "Incident")) == "incident-analysis"
    assert entry_workflow_for(item("servicenow", "incident")) == "incident-analysis"
    assert entry_workflow_for(item("jira", "Bug")) == "jira-intake-triage"
    assert entry_workflow_for(item("servicenow", "sc_req_item")) == "jira-intake-triage"
    assert entry_workflow_for(item("jira", None)) == "jira-intake-triage"
    assert entry_workflow_for(None) == "jira-intake-triage"
    switched_off = effective_routes({"incident": None})
    assert entry_workflow_for(item("jira", "Incident"), switched_off) == "jira-intake-triage"
    assert entry_workflow_for(item("jira", "Incident"), effective_routes({"incident": "review-and-pr"})) == (
        "review-and-pr")


@pytest.mark.asyncio
async def test_the_run_start_preselects_the_entry_workflow_and_starts_nothing(client, auth_headers, db):
    incident = await _item(db, source_type="servicenow", issue_type="incident")
    story = await _item(db, issue_type="Story")
    await db.commit()
    for item, expected in ((incident, "incident-analysis"), (story, "jira-intake-triage")):
        answer = await client.get(f"/api/v1/workflow-runs/startable?work_item_id={item.id}", headers=auth_headers)
        assert answer.status_code == 200 and answer.json()["entry_workflow"] == expected
        runs = (await db.execute(select(func.count()).select_from(WorkflowRun).where(
            WorkflowRun.work_item_id == item.id))).scalar_one()
        assert runs == 0
    plain = await client.get("/api/v1/workflow-runs/startable", headers=auth_headers)
    assert "entry_workflow" not in plain.json()


@pytest.mark.asyncio
async def test_the_workspace_routes_are_read_and_replaced_through_the_api(client, auth_headers, db):
    workspace_id = await seed_workspace(db)
    await db.commit()
    path = f"/api/v1/workflow-runs/triage-routing?project_id={workspace_id}"
    read = (await client.get(path, headers=auth_headers)).json()
    assert (read["source"], read["routes"], read["effective"]) == ("default", {}, DEFAULT_ROUTES)
    saved = await client.put(path, headers=auth_headers, json={"routes": {"feature": "review-and-pr", "bug": None}})
    assert saved.status_code == 200, saved.text
    assert saved.json()["routes"] == {"feature": "review-and-pr", "bug": None}
    assert saved.json()["effective"]["bug"] is None and saved.json()["source"] == "workspace"
    replaced = (await client.put(path, headers=auth_headers, json={"routes": {"task": "review-and-pr"}})).json()
    assert replaced["routes"] == {"task": "review-and-pr"}  # replaced, never merged with the earlier routes
    refused = await client.put(path, headers=auth_headers, json={"routes": {"feature": "jira-intake-triage"}})
    assert refused.status_code == 422
    assert refused.json()["detail"]["errors"][0]["code"] == "route_to_triage"
