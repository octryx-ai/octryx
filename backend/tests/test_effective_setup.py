"""Effective setup (A1): the dry run of the real run preparation, its parts, and the turn comparison."""

from __future__ import annotations

import pytest
from sqlalchemy import func, select

from app.models import Session as ChatSession
from app.services.effective_setup import (
    chat_effective_setup,
    compare_prompt_refs,
    external_effective_setup,
    latest_turn_record,
    session_setup_inputs,
)
from tests.phased_workflow_fixtures import phased_definition, publish_phased
from tests.product_run_chat_binding_support import FINAL_RESPONSE, _session, _turn
from tests.product_run_chat_support import world  # noqa: F401 - fixture
from tests.prompt_catalog_contract_support import _publish

PART_ORDER = ["system_texts", "agent", "instructions", "workflow", "skills", "tools", "approvals"]


async def _session_count(db) -> int:
    return int((await db.execute(select(func.count()).select_from(ChatSession))).scalar_one())


@pytest.mark.asyncio
async def test_the_dry_run_returns_every_part_in_order_and_persists_nothing(db) -> None:
    session = await _session(db)
    before = await _session_count(db)

    setup = await chat_effective_setup(db, user_id=session.user_id, project_id=session.project_id)

    assert [part["id"] for part in setup["parts"]] == PART_ORDER
    assert setup["summary"]["capability"]["class"] == "read_only"
    assert setup["prompt_refs"], "the system prompt renders catalog keys"
    assert setup["budget"]["total"] > 0
    workflow = next(part for part in setup["parts"] if part["id"] == "workflow")
    assert workflow["details"]["selected"] is False
    assert await _session_count(db) == before


@pytest.mark.asyncio
async def test_a_phased_workflow_key_selects_no_workflow_for_the_chat_turn(db) -> None:
    """A phased workflow never runs inside a chat turn: its key holds the turn for the run's start confirmation."""
    session = await _session(db)
    key = await publish_phased(db, phased_definition())

    setup = await chat_effective_setup(db, user_id=session.user_id, project_id=session.project_id, workflow_key=key)

    workflow = next(part for part in setup["parts"] if part["id"] == "workflow")
    assert workflow["details"]["selected"] is False
    assert workflow["details"]["state"] == "needs_confirmation"
    assert setup["summary"]["workflow_key"] == ""


@pytest.mark.asyncio
async def test_an_unknown_workflow_key_is_shown_as_unknown_not_guessed(db) -> None:
    session = await _session(db)

    setup = await chat_effective_setup(
        db, user_id=session.user_id, project_id=session.project_id, workflow_key="no-such-workflow"
    )

    workflow = next(part for part in setup["parts"] if part["id"] == "workflow")
    assert workflow["details"]["selected"] is False
    assert workflow["details"]["state"] == "unknown_key"


@pytest.mark.asyncio
async def test_a_real_turn_matches_the_dry_run_until_an_override_is_published(db, world) -> None:  # noqa: F811
    session = await _session(db)
    world["script"] = [FINAL_RESPONSE]
    async for _event in _turn(db, session):
        pass
    inputs = session_setup_inputs(session)
    record = await latest_turn_record(db, session.id)
    assert record is not None and record["prompt_refs"]

    setup = await chat_effective_setup(db, user_id=inputs["user_id"], project_id=inputs["project_id"])
    comparison = compare_prompt_refs(setup["prompt_refs"], record["prompt_refs"], catalog_refs=setup["catalog_refs"])
    assert comparison["matches"] is True
    assert comparison["same"] > 0

    await _publish(db, "system.dynamic_context_prompts", "## Dynamic Context Prompts\n- Changed.",
                   scope_type="workspace", scope_id=session.project_id)
    after = await chat_effective_setup(db, user_id=inputs["user_id"], project_id=inputs["project_id"])
    changed = compare_prompt_refs(after["prompt_refs"], record["prompt_refs"], catalog_refs=after["catalog_refs"])
    assert changed["matches"] is False
    assert [item["key"] for item in changed["keys"] if item["state"] == "changed"] == ["system.dynamic_context_prompts"]


@pytest.mark.asyncio
async def test_octryx_claude_setup_reads_the_mcp_contract_and_instructions(db) -> None:
    session = await _session(db)
    key = await publish_phased(db, phased_definition())

    setup = await external_effective_setup(db, project_id=session.project_id, workflow_key=key)

    assert [part["id"] for part in setup["parts"]] == PART_ORDER
    texts = setup["parts"][0]
    assert texts["details"]["keys"][0]["key"] == "knowledge.mcp.instructions"
    workflow = setup["parts"][3]
    assert workflow["details"]["selected"] is False
    assert key in workflow["details"]["available_workflow_keys"]
    assert setup["summary"]["profile_status"] == "workflow_run_required"
    assert setup["summary"]["capability"]["class"] == "read_only"


@pytest.mark.asyncio
async def test_the_api_is_admin_only_and_answers_the_session_view(client, auth_headers, db, world) -> None:  # noqa: F811
    session = await _session(db)
    key = await publish_phased(db, phased_definition())
    world["script"] = [FINAL_RESPONSE]
    async for _event in _turn(db, session):
        pass

    response = await client.get(
        "/api/v1/effective-setup", params={"project_id": session.project_id}, headers=auth_headers
    )
    assert response.status_code == 200
    assert [part["id"] for part in response.json()["parts"]] == PART_ORDER

    options = await client.get(
        "/api/v1/effective-setup/options", params={"project_id": session.project_id}, headers=auth_headers
    )
    assert options.status_code == 200
    assert any(item["key"] == key for item in options.json()["workflows"])

    by_session = await client.get(f"/api/v1/effective-setup/sessions/{session.id}", headers=auth_headers)
    assert by_session.status_code == 200
    assert by_session.json()["comparison"]["matches"] is True

    bad_runtime = await client.get("/api/v1/effective-setup", params={"runtime": "other"}, headers=auth_headers)
    assert bad_runtime.status_code == 422
    assert (await client.get("/api/v1/effective-setup")).status_code in {401, 403}
