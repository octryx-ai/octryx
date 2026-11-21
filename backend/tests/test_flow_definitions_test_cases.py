"""Flow test cases in batches and partial runs, assertion failures and run quality evaluation."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.models import Project, WorkflowCheckResult
from tests.flow_definitions_support import _flow_payload


@pytest.mark.asyncio
async def test_flow_definition_api_test_cases_batch_and_partial_run(client, auth_headers, db):
    project = (await db.execute(select(Project).where(Project.name == "acme-orders"))).scalar_one()
    payload = {
        **_flow_payload(project.id),
        "key": "iteration-v2-flow",
        "name": "Iteration V2 Flow",
        "definition": {
            "schema_version": "2.0",
            "nodes": [
                {"id": "input", "type": "trigger", "config": {"trigger_type": "manual"}},
                {"id": "out", "type": "output", "input_schema": {"result": "string"}},
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
    flow = create_response.json()
    flow_id = flow["id"]
    version_id = flow["versions"][0]["id"]

    create_case_response = await client.post(
        f"/api/v1/flows/{flow_id}/test-cases",
        headers=auth_headers,
        json={
            "name": "Basic request",
            "project_id": project.id,
            "input": {"request": "case one"},
            "expected_output": {"final": {"result": {"result": "case one"}}},
            "tags": ["smoke"],
        },
    )
    create_failing_case_response = await client.post(
        f"/api/v1/flows/{flow_id}/test-cases",
        headers=auth_headers,
        json={
            "name": "Wrong expectation",
            "project_id": project.id,
            "input": {"request": "case two"},
            "expected_output": {"final": {"result": {"result": "not case two"}}},
        },
    )
    list_response = await client.get(f"/api/v1/flows/{flow_id}/test-cases", headers=auth_headers)
    assert create_case_response.status_code == 200, create_case_response.text
    assert create_failing_case_response.status_code == 200, create_failing_case_response.text
    assert list_response.status_code == 200, list_response.text
    test_case = create_case_response.json()
    failing_test_case = create_failing_case_response.json()
    assert list_response.json()["items"][0]["id"] == test_case["id"]

    run_case_response = await client.post(
        f"/api/v1/flows/{flow_id}/test-cases/{test_case['id']}/run",
        headers=auth_headers,
    )
    batch_response = await client.post(
        f"/api/v1/flows/{flow_id}/test-cases/batch-run",
        headers=auth_headers,
        json={"test_case_ids": [test_case["id"], failing_test_case["id"]]},
    )
    partial_response = await client.post(
        f"/api/v1/flows/versions/{version_id}/partial-run",
        headers=auth_headers,
        json={"node_id": "out", "project_id": project.id, "initial_input": {"result": "partial"}},
    )

    assert run_case_response.status_code == 200, run_case_response.text
    assert batch_response.status_code == 200, batch_response.text
    assert partial_response.status_code == 200, partial_response.text
    assert run_case_response.json()["status"] == "completed"
    assert run_case_response.json()["passed"] is True
    assert run_case_response.json()["evaluation_summary"]["status"] == "passed"
    assert run_case_response.json()["trace"]["node_runs"][0]["node_id"] == "input"
    assert batch_response.json()["count"] == 2
    assert batch_response.json()["passed"] == 1
    assert batch_response.json()["failed"] == 1
    failed_result = next(result for result in batch_response.json()["results"] if result["test_case"]["id"] == failing_test_case["id"])
    assert failed_result["passed"] is False
    assert failed_result["evaluation_summary"]["results"][0]["operator"] == "matches_expected_output"
    assert [(item["node_id"], item["status"]) for item in partial_response.json()["node_runs"]] == [
        ("out", "completed"),
    ]
    assert partial_response.json()["run"]["flow_node_id"] == "out"


@pytest.mark.asyncio
async def test_flow_definition_api_test_case_assertions_report_batch_failures(client, auth_headers, db):
    project = (await db.execute(select(Project).where(Project.name == "acme-orders"))).scalar_one()
    payload = {
        **_flow_payload(project.id),
        "key": "iteration-v2-assertion-flow",
        "name": "Iteration V2 Assertion Flow",
        "definition": {
            "schema_version": "2.0",
            "nodes": [
                {"id": "input", "type": "trigger", "config": {"trigger_type": "manual"}},
                {"id": "out", "type": "output", "input_schema": {"result": "string"}},
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
    flow_id = create_response.json()["id"]

    create_case_response = await client.post(
        f"/api/v1/flows/{flow_id}/test-cases",
        headers=auth_headers,
        json={
            "name": "Mismatching expected output",
            "project_id": project.id,
            "input": {"request": "actual"},
            "expected_output": {"final": {"result": "expected"}},
        },
    )
    assert create_case_response.status_code == 200, create_case_response.text

    batch_response = await client.post(
        f"/api/v1/flows/{flow_id}/test-cases/batch-run",
        headers=auth_headers,
        json={"test_case_ids": [create_case_response.json()["id"]]},
    )

    assert batch_response.status_code == 200, batch_response.text
    batch = batch_response.json()
    assert batch["count"] == 1
    assert batch["passed"] == 0
    assert batch["failed"] == 1
    assert batch["results"][0]["evaluation_summary"]["status"] == "failed"
    assert batch["results"][0]["assertion_results"][0]["passed"] is False


@pytest.mark.asyncio
async def test_flow_run_quality_evaluation_api(client, auth_headers, db):
    project = (await db.execute(select(Project).where(Project.name == "acme-orders"))).scalar_one()
    payload = {
        **_flow_payload(project.id),
        "key": "quality-v2-flow",
        "name": "Quality V2 Flow",
        "definition": {
            "schema_version": "2.0",
            "nodes": [
                {"id": "input", "type": "trigger", "config": {"trigger_type": "manual"}},
                {"id": "out", "type": "output", "input_schema": {"result": "string"}},
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
    flow = create_response.json()
    version_id = flow["versions"][0]["id"]
    run_response = await client.post(
        f"/api/v1/flows/versions/{version_id}/run",
        headers=auth_headers,
        json={"project_id": project.id, "initial_input": {"request": "quality"}},
    )
    assert run_response.status_code == 200, run_response.text
    run_id = run_response.json()["run"]["id"]
    quality_response = await client.get(f"/api/v1/flows/runs/{run_id}/quality", headers=auth_headers)
    evaluate_response = await client.post(
        f"/api/v1/flows/runs/{run_id}/evaluate",
        headers=auth_headers,
        json={},
    )
    # The learning-candidate capture wrote the retired Agent Learning store.
    learning_response = await client.post(
        f"/api/v1/flows/runs/{run_id}/learning-candidate",
        headers=auth_headers,
        json={},
    )

    assert quality_response.status_code == 200, quality_response.text
    assert quality_response.json()["run"]["id"] == run_id
    assert evaluate_response.status_code == 200, evaluate_response.text
    assert evaluate_response.json()["evaluation_run"]["status"] == "completed"
    assert evaluate_response.json()["quality_summary"]["evaluation_runs"][0]["id"] == evaluate_response.json()["evaluation_run"]["id"]
    assert learning_response.status_code == 404
    # A6: the canvas evaluation is stored as a check result of runtime "canvas"; no evaluation suite.
    stored = await db.get(WorkflowCheckResult, evaluate_response.json()["evaluation_run"]["id"])
    assert stored is not None and stored.runtime == "canvas" and stored.trace_id == run_id
