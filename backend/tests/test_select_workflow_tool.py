"""The select_workflow meta tool answers the explicit state of a key; it never adopts a contract in the turn."""

from __future__ import annotations

import pytest

from app.services.workflow_routing.model_catalog import build_model_workflow_catalog
from app.tools.context import ToolContext
from app.tools.workflow_tools import SelectWorkflowTool

PHASED_KEY = "incident-analysis"
PROMPT = "Analyse the checkout incident from last night."


def _context(db, *, snapshot: dict | None = None) -> ToolContext:
    return ToolContext(
        user_id="user-1",
        project_ids=[],
        roles=["admin"],
        session_id="session-1",
        project_config={},
        current_user_message=PROMPT,
        db=db,
        turn_context_snapshot=snapshot or {},
    )


@pytest.mark.asyncio
async def test_a_phased_key_needs_the_users_start_confirmation(db):
    result = await SelectWorkflowTool().execute({"workflow_key": PHASED_KEY}, _context(db))

    assert (result["status"], result["reason"]) == ("needs_confirmation", "workflow_run_required")
    assert result["workflow_key"] == PHASED_KEY
    assert "workflow_contract" not in result
    assert any(entry["workflow_key"] == PHASED_KEY for entry in result["available_workflows"])


@pytest.mark.asyncio
async def test_select_workflow_is_deterministic(db):
    first = await SelectWorkflowTool().execute({"workflow_key": PHASED_KEY}, _context(db))
    second = await SelectWorkflowTool().execute({"workflow_key": PHASED_KEY}, _context(db))
    assert first == second


@pytest.mark.asyncio
async def test_select_workflow_unknown_key_returns_catalog(db):
    result = await SelectWorkflowTool().execute({"workflow_key": "does-not-exist"}, _context(db))

    assert "status" not in result
    assert "does-not-exist" in result["error"]
    catalog = result["available_workflows"]
    # The whole published catalog, however many workflows are published (not a pinned count).
    published = await build_model_workflow_catalog(db, project_id=None)
    assert [entry["workflow_key"] for entry in catalog] == [entry["workflow_key"] for entry in published]
    assert any(entry["workflow_key"] == PHASED_KEY for entry in catalog)


@pytest.mark.asyncio
async def test_select_workflow_respects_the_users_no_workflow_choice(db):
    snapshot = {
        "request_analysis": {
            "workflow_routing_policy_resolution": {
                "workflow_proposal": {"status": "none", "reason_code": "user_selected_no_workflow"},
            }
        }
    }

    result = await SelectWorkflowTool().execute({"workflow_key": PHASED_KEY}, _context(db, snapshot=snapshot))

    assert result["status"] == "user_selected_no_workflow"
    assert "available_workflows" not in result


@pytest.mark.asyncio
async def test_keyless_select_workflow_escalates_instead_of_repeating(db) -> None:
    """Identical key-less retries must escalate rather than looping on a dead turn."""
    tool = SelectWorkflowTool()
    context = _context(db, snapshot={})

    first = await tool.execute({}, context)
    assert first["error"].startswith("workflow_key is required")
    assert first["available_workflows"], "catalog must ride along on the first miss"
    assert first["keyless_attempt"] == 1
    assert "required_call_syntax" not in first

    second = await tool.execute({}, context)
    assert second["keyless_attempt"] == 2
    assert "select_workflow with arguments" in second["required_call_syntax"]

    third = await tool.execute({}, context)
    assert third["keyless_attempt"] == 3
    assert "Do not call select_workflow again without workflow_key" in third["next_step"]
