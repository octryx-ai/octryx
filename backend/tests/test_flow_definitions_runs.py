"""The flow definition API runs v2 flows, exposes redacted run and node traces and resumes paused approval flows."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.models import Project
from tests.flow_definitions_support import _flow_payload


@pytest.mark.asyncio
async def test_flow_definition_api_runs_v2_flow_and_returns_node_runs(client, auth_headers, db):
    project = (await db.execute(select(Project).where(Project.name == "acme-orders"))).scalar_one()
    payload = {
        **_flow_payload(project.id),
        "key": "runnable-v2-flow",
        "name": "Runnable V2 Flow",
        "definition": {
            "schema_version": "2.0",
            "nodes": [
                {"id": "input", "type": "trigger", "config": {"trigger_type": "manual"}},
                {"id": "out", "type": "output"},
            ],
            "edges": [
                {
                    "source_node_id": "input",
                    "target_node_id": "out",
                    "source_field": "request",
                    "target_field": "result",
                }
            ],
        },
    }
    create_response = await client.post("/api/v1/flows", headers=auth_headers, json=payload)
    assert create_response.status_code == 200, create_response.text
    version_id = create_response.json()["versions"][0]["id"]

    run_response = await client.post(
        f"/api/v1/flows/versions/{version_id}/run",
        headers=auth_headers,
        json={"project_id": project.id, "initial_input": {"request": "from-api"}},
    )

    assert run_response.status_code == 200, run_response.text
    body = run_response.json()
    assert body["run"]["status"] == "completed"
    assert body["run"]["merged_output_json"]["final"] == {"result": {"result": "from-api"}}
    assert [(item["node_id"], item["status"]) for item in body["node_runs"]] == [
        ("input", "completed"),
        ("out", "completed"),
    ]
    assert body["node_runs"][0]["input"] == {"request": "from-api"}


@pytest.mark.asyncio
async def test_flow_definition_api_exposes_redacted_run_and_node_trace(client, auth_headers, db):
    project = (await db.execute(select(Project).where(Project.name == "acme-orders"))).scalar_one()
    payload = {
        **_flow_payload(project.id),
        "key": "redacted-trace-v2-flow",
        "name": "Redacted Trace V2 Flow",
        "definition": {
            "schema_version": "2.0",
            "nodes": [
                {"id": "input", "type": "trigger", "config": {"trigger_type": "manual"}},
                {"id": "out", "type": "output"},
            ],
            "edges": [
                {
                    "source_node_id": "input",
                    "target_node_id": "out",
                    "source_field": "request",
                    "target_field": "result",
                }
            ],
        },
    }
    create_response = await client.post("/api/v1/flows", headers=auth_headers, json=payload)
    assert create_response.status_code == 200, create_response.text
    version_id = create_response.json()["versions"][0]["id"]
    run_response = await client.post(
        f"/api/v1/flows/versions/{version_id}/run",
        headers=auth_headers,
        json={"project_id": project.id,
              "initial_input": {"request": "trace me", "api_key": "super-secret-value"}},
    )
    assert run_response.status_code == 200, run_response.text
    run_body = run_response.json()
    run_id = run_body["run"]["id"]
    node_run_id = run_body["node_runs"][0]["id"]

    trace_response = await client.get(f"/api/v1/flows/runs/{run_id}/trace", headers=auth_headers)
    node_response = await client.get(
        f"/api/v1/flows/runs/{run_id}/node-runs/{node_run_id}",
        headers=auth_headers,
    )

    assert trace_response.status_code == 200, trace_response.text
    assert node_response.status_code == 200, node_response.text
    trace_body = trace_response.json()
    node_body = node_response.json()
    assert trace_body["run"]["status"] == "completed"
    assert trace_body["node_runs"][0]["input"]["request"] == "trace me"
    assert trace_body["node_runs"][0]["input"]["api_key"] == "[redacted]"
    assert node_body["node_run"]["input"]["api_key"] == "[redacted]"
    assert node_body["node_run"]["duration_ms"] is not None
    assert node_body["node_run"]["trace_refs"]["node_type"] == "trigger"


@pytest.mark.asyncio
async def test_flow_definition_api_resumes_paused_approval_flow(client, auth_headers, db):
    project = (await db.execute(select(Project).where(Project.name == "acme-orders"))).scalar_one()
    payload = {
        **_flow_payload(project.id),
        "key": "approval-resume-v2-flow",
        "name": "Approval Resume V2 Flow",
        "definition": {
            "schema_version": "2.0",
            "nodes": [
                {"id": "input", "type": "trigger", "config": {"trigger_type": "manual"}},
                {"id": "approval", "type": "approval", "config": {"title": "Approve API resume"}},
                {"id": "out", "type": "output", "input_schema": {"approved": "boolean"}},
            ],
            "edges": [
                {"source_node_id": "input", "target_node_id": "approval", "source_field": "request", "target_field": "proposal"},
                {
                    "source_node_id": "approval",
                    "target_node_id": "out",
                    "source_field": "approved",
                    "target_field": "approved",
                },
            ],
        },
    }
    create_response = await client.post("/api/v1/flows", headers=auth_headers, json=payload)
    assert create_response.status_code == 200, create_response.text
    version_id = create_response.json()["versions"][0]["id"]
    run_response = await client.post(
        f"/api/v1/flows/versions/{version_id}/run",
        headers=auth_headers,
        json={"project_id": project.id, "initial_input": {"request": "needs approval"}},
    )
    assert run_response.status_code == 200, run_response.text
    paused_body = run_response.json()
    assert paused_body["run"]["status"] == "paused"
    approval_id = paused_body["node_runs"][1]["output"]["approval_id"]

    unauthenticated_resume = await client.post(
        f"/api/v1/flows/runs/{paused_body['run']['id']}/resume",
        json={"decision": "approve", "approval_id": approval_id},
    )
    resume_response = await client.post(
        f"/api/v1/flows/runs/{paused_body['run']['id']}/resume",
        headers=auth_headers,
        json={
            "decision": "approve",
            "approval_id": approval_id,
            "human_input": {"operator_note": "approved from test"},
        },
    )

    assert unauthenticated_resume.status_code == 401
    assert resume_response.status_code == 200, resume_response.text
    resumed = resume_response.json()
    assert resumed["run"]["status"] == "completed"
    assert [(item["node_id"], item["status"]) for item in resumed["node_runs"]] == [
        ("input", "completed"),
        ("approval", "completed"),
        ("out", "completed"),
    ]
    assert resumed["run"]["merged_output_json"]["final"] == {"result": {"approved": True}}
