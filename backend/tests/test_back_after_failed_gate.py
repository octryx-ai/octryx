"""Back in a phase after its gate failed, the agent reads that gate's failed
checks first: in the pass's prompt (once), at every Stop that finds the phase not done, and in the Stop summary only the
loops the run took."""

from __future__ import annotations

import pytest

from app.services.prompt_catalog import prompt_set_scope, seed_prompt_set
from app.services.workflow_runs.binding import run_turn_resolution
from app.services.workflow_runs.graph import graph_for_run
from app.services.workflow_runs.octryx import gate_failure
from app.services.workflow_runs.octryx.contract import contract_summary
from app.services.workflow_runs.records import new_chat_session, start_run
from tests.phased_workflow_fixtures import admin_user, phase_turn, phased_definition, publish_phased, run_workspace


async def _back_in_work(db):
    admin = await admin_user(db)
    workspace_id = await run_workspace(db, admin)
    session = await new_chat_session(db, admin, workspace_id)
    run = await start_run(db, user=admin, workflow_key=await publish_phased(db, phased_definition(max_iterations=2)),
                          project_id=workspace_id,
                          session=session)
    resolution = await run_turn_resolution(db, session, user_message="Collect it.")
    await phase_turn(db, session.id, resolution, ["knowledge_search"])  # passes; the gate wants knowledge_read
    return run


@pytest.mark.asyncio
async def test_the_failed_gate_is_the_first_thing_the_phase_reads_when_the_run_is_back(db):
    from app.services.workflow_runs.octryx.continuation_prompts import _prompt
    from app.services.workflow_runs.octryx.run_session import next_phase_prompt

    run = await _back_in_work(db)
    assert run.current_node_id == "work"
    found = gate_failure.current(run, "work")
    assert found["gate"] == "Evidence read" and "A source was read" in found["failed"]
    node = (await graph_for_run(db, run)).nodes["work"]
    with prompt_set_scope(seed_prompt_set()):
        prompt = next_phase_prompt(run, node)  # the same-turn loop back (size class phase_change: same_turn)
        assert prompt.startswith("Gate 'Evidence read' failed: A source was read")
        assert "moves on to its next phase" not in prompt
        assert "Gate 'Evidence read' failed" not in _prompt(run, node)  # once
        assert gate_failure.stop_line(run, "work").startswith("Back here because gate 'Evidence read' failed")


@pytest.mark.asyncio
async def test_a_passed_gate_clears_it_and_the_summary_names_only_loops_taken(db):
    run = await _back_in_work(db)
    assert gate_failure.current(run, "work") is not None
    gate_failure.clear(run)
    assert gate_failure.stop_line(run, "work") == ""
    loops = [{"title": "Never taken", "iteration": 1, "of": 3}, {"title": "Rework", "iteration": 2, "of": 3}]
    summary = contract_summary({"run": {"workflow_key": "w"}, "phase": {"title": "Work", "capability_class": "change"},
                                "loop": loops})
    assert "Rework 2/3" in summary and "Never taken" not in summary
