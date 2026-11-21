"""Explicit workflow selection: a workflow_key resolves to an explicit state, never a guessed contract."""

from __future__ import annotations

import pytest

from app.services.workflow_routing.explicit_selection import resolve_explicit_workflow_selection
from app.services.workflow_runs.seeding import phased_seeds
from app.services.workflow_runs.start_trigger import STARTED_BY_PULL_REQUEST, started_by
from tests.explicit_workflow_selection_support import _profile_for_resolution

PHASED_KEY = "incident-analysis"


@pytest.mark.asyncio
async def test_a_phased_key_resolves_deterministically_to_a_workflow_run(db):
    first = await resolve_explicit_workflow_selection(db, workflow_key=PHASED_KEY, project_id=None)
    second = await resolve_explicit_workflow_selection(db, workflow_key=PHASED_KEY, project_id=None)

    assert first == second
    assert first["status"] == "workflow_run_required"
    assert first["workflow_key"] == PHASED_KEY
    assert first["execution_kind"] == "phased"
    # A phased workflow is never a chat turn's contract.
    assert first["workflow_contract"] is None and first["tool_policy"] is None

    profile = _profile_for_resolution(first)
    assert profile.status == "needs_clarification"
    assert profile.decision_source == "workflow_run_required"


@pytest.mark.asyncio
async def test_unknown_workflow_key_is_explicit_error_without_fallback(db):
    resolution = await resolve_explicit_workflow_selection(db, workflow_key="does-not-exist", project_id=None)

    assert resolution["source"] == "explicit_workflow_key"
    assert resolution["status"] == "unknown_key"
    assert resolution["workflow_id"] is None
    assert resolution["workflow_contract"] is None
    assert resolution["tool_policy"] is None
    assert PHASED_KEY in resolution["available_workflow_keys"]
    assert PHASED_KEY in resolution["unmatched_reason"]
    assert "does-not-exist" in resolution["unmatched_reason"]

    profile = _profile_for_resolution(resolution)
    assert profile.status == "needs_clarification"
    assert profile.decision_source == "explicit_workflow_key"
    assert PHASED_KEY in profile.reason


@pytest.mark.asyncio
async def test_chat_workflows_endpoint_lists_only_the_phased_workflows(client, auth_headers):
    resp = await client.get("/chat/api/workflows", headers=auth_headers)

    assert resp.status_code == 200
    workflows = resp.json()["workflows"]
    # Every shipped phased workflow seed, but none a pull request starts (its Start box says so).
    offered = {seed["key"] for seed in phased_seeds() if started_by(seed["definition"]) != STARTED_BY_PULL_REQUEST}
    offered.add("feature-delivery-tdd")  # B, which the suite publishes as an admin would, is offered like any other
    assert {item["source"] for item in workflows} == {"phased"}
    assert {item["key"] for item in workflows} == offered


@pytest.mark.asyncio
async def test_chat_workflows_endpoint_requires_auth(client):
    resp = await client.get("/chat/api/workflows")
    assert resp.status_code in {303, 401, 403}
