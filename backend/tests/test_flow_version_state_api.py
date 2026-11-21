"""Flow version run/publish/unpublish refuse unknown ids and wrong states explicitly.

Every refusal is a 404/409 with a closed ``reason``; none of them may surface as a 500.
"""

from __future__ import annotations

import pytest

from tests.knowledge_evidence_seed_support import seed_workspace

_UNKNOWN_VERSION_ID = "00000000-0000-0000-0000-000000000000"


def _runnable_flow(key: str) -> dict[str, object]:
    return {
        "key": key,
        "name": f"State {key}",
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


async def _create_version(client, auth_headers, key: str) -> tuple[str, str]:
    created = await client.post("/api/v1/flows", headers=auth_headers, json=_runnable_flow(key))
    assert created.status_code == 200, created.text
    body = created.json()
    return body["id"], body["versions"][0]["id"]


@pytest.fixture
async def workspace_id(db) -> str:
    """The Workspace a run starts in (a DAG run without one is refused first, ``flow_orchestration.start_scope``)."""
    return await seed_workspace(db)


def _reason(response) -> str:
    return response.json()["detail"]["reason"]


@pytest.mark.asyncio
@pytest.mark.parametrize("action", ["run", "publish", "unpublish", "partial-run"])
async def test_unknown_version_is_a_closed_404(client, auth_headers, workspace_id, action):
    response = await client.post(
        f"/api/v1/flows/versions/{_UNKNOWN_VERSION_ID}/{action}",
        headers=auth_headers,
        json={"node_id": "out", "project_id": workspace_id} if action == "partial-run" else {"project_id": workspace_id},
    )

    assert response.status_code == 404, response.text
    assert _reason(response) == "flow_version_not_found"


@pytest.mark.asyncio
async def test_publish_and_unpublish_refuse_the_wrong_state(client, auth_headers, workspace_id):
    _, version_id = await _create_version(client, auth_headers, "state-lifecycle")

    draft_unpublish = await client.post(f"/api/v1/flows/versions/{version_id}/unpublish", headers=auth_headers)
    assert draft_unpublish.status_code == 409, draft_unpublish.text
    assert _reason(draft_unpublish) == "flow_version_not_published"

    published = await client.post(f"/api/v1/flows/versions/{version_id}/publish", headers=auth_headers)
    assert published.status_code == 200, published.text

    republished = await client.post(f"/api/v1/flows/versions/{version_id}/publish", headers=auth_headers)
    assert republished.status_code == 409, republished.text
    assert _reason(republished) == "flow_version_already_published"

    unpublished = await client.post(f"/api/v1/flows/versions/{version_id}/unpublish", headers=auth_headers)
    assert unpublished.status_code == 200, unpublished.text

    unpublished_again = await client.post(f"/api/v1/flows/versions/{version_id}/unpublish", headers=auth_headers)
    assert unpublished_again.status_code == 409, unpublished_again.text
    assert _reason(unpublished_again) == "flow_version_not_published"

    # An unpublished (archived) version does not run, but an active flow may publish it again.
    archived_run = await client.post(
        f"/api/v1/flows/versions/{version_id}/run",
        headers=auth_headers,
        json={"project_id": workspace_id, "initial_input": {"request": "x"}},
    )
    assert archived_run.status_code == 409, archived_run.text
    assert _reason(archived_run) == "flow_version_archived"

    archived_partial = await client.post(
        f"/api/v1/flows/versions/{version_id}/partial-run",
        headers=auth_headers,
        json={"node_id": "out", "project_id": workspace_id},
    )
    assert archived_partial.status_code == 409, archived_partial.text
    assert _reason(archived_partial) == "flow_version_archived"

    restored = await client.post(f"/api/v1/flows/versions/{version_id}/publish", headers=auth_headers)
    assert restored.status_code == 200, restored.text


@pytest.mark.asyncio
async def test_a_rejected_flow_cannot_be_published(client, auth_headers):
    flow_id, version_id = await _create_version(client, auth_headers, "state-rejected")
    rejected = await client.post(f"/api/v1/flows/{flow_id}/archive", headers=auth_headers)
    assert rejected.status_code == 200, rejected.text

    publish = await client.post(f"/api/v1/flows/versions/{version_id}/publish", headers=auth_headers)

    assert publish.status_code == 409, publish.text
    assert _reason(publish) == "flow_archived"


@pytest.mark.asyncio
async def test_a_draft_version_runs_as_a_trace(client, auth_headers, workspace_id):
    _, version_id = await _create_version(client, auth_headers, "state-draft-run")

    run = await client.post(
        f"/api/v1/flows/versions/{version_id}/run",
        headers=auth_headers,
        json={"project_id": workspace_id, "initial_input": {"request": "draft"}},
    )

    assert run.status_code == 200, run.text
    assert run.json()["run"]["status"] == "completed"

