"""A red hands-on test sends the run back into the building phase with what failed: the turn's prompt names the
building phase and points at phase.hands_on_failure, and the run contract carries exactly the failed scenarios
(a generic text named after the hands-on step, with no failed scenario, leaves the session changing nothing:
hands_on_unchanged)."""

from __future__ import annotations

import copy
from types import SimpleNamespace

import pytest

from app.services.devices.job_events import apply_event
from app.services.devices.job_offer import offer_body
from app.services.workflow_runs.hands_on.step import CONTEXT_KEY as HANDS_ON_KEY
from app.services.workflow_runs.octryx import continuation_prompts
from app.services.workflow_runs.octryx.continuation_marker import CONTEXT_KEY
from app.services.workflow_runs.octryx.contract import run_contract
from tests.phased_workflow_fixtures import PHASE
from tests.workflow_run_octryx_continuation_support import DEFINITION, _confirm, _device_run, _jobs, _reenter

BUILD = copy.deepcopy(PHASE)
BUILD["workflow_contract"]["capability_class"] = "change"
HANDS_ON = {
    "execution_kind": "phased",
    "nodes": [*DEFINITION["nodes"][:2],
              {"id": "work", "type": "phase", "label": "Implement", "config": BUILD},
              {"id": "hands_on", "type": "platform_action", "label": "Hands-on test of the built app",
               "config": {"action": "hands_on.run"}},
              *DEFINITION["nodes"][3:]],
    "edges": [*DEFINITION["edges"][:4],
              {"id": "e4", "source_node_id": "work", "target_node_id": "hands_on"},
              {"id": "e-hands-on", "source_node_id": "hands_on", "target_node_id": "done", "when": "succeeded"},
              {"id": "e-hands-on-red", "source_node_id": "hands_on", "target_node_id": "work", "when": "failed",
               "kind": "loop", "max_iterations": 3}],
}
RESULTS = [
    {"id": "S1", "title": "Last brew is shown", "passed": False,
     "failed_step": {"index": 3, "action": "expect text", "expected": "Last brew"}},
    {"id": "S2", "title": "A new bean is listed", "passed": False,
     "failed_step": {"index": 2, "action": "expect text", "expected": "Created: Bean 1"}},
    {"id": "S3", "title": "The settings page opens", "passed": True},
]


@pytest.mark.asyncio
async def test_a_red_hands_on_test_goes_back_into_the_building_phase_with_exactly_its_failed_scenarios(db):
    admin, _device, thread, run = await _device_run(db, definition=HANDS_ON)
    await _confirm(db, run, admin)
    [job] = await _jobs(db, thread)
    await apply_event(db, job, "job_event", {"kind": "session", "claude_session_id": "claude-build-1"}, limits={})
    await apply_event(db, job, "job_accepted", {"turn_id": job.turn_id}, limits={})

    # The building phase passed: the hands-on step's turn is the building phase's and resumes its session.
    await _reenter(db, run, "hands_on", runtime_step=True)
    assert run.context[CONTEXT_KEY]["then_phase"] == "work"
    await apply_event(db, job, "turn_finished", {"turn_id": job.turn_id, "status": "success"}, limits={})
    assert offer_body(job, limits={})["resume_session_id"] == "claude-build-1"
    # The launcher starts this agent only after a red test: the prompt names the building phase, not the step.
    assert "Phase 'Implement'" in job.turn_prompt and "hands-on test is red" in job.turn_prompt
    assert "phase.hands_on_failure" in job.turn_prompt and "Hands-on test of the built app" not in job.turn_prompt

    # Red with two failed scenarios: the loop goes back to the building phase.
    run.context = {**dict(run.context or {}), HANDS_ON_KEY: {"state": "red", "node_id": "hands_on", "results": RESULTS,
                                                             "problem": "2 of 3 scenarios failed"}}
    await apply_event(db, job, "job_accepted", {"turn_id": job.turn_id}, limits={})
    await _reenter(db, run, "work")

    phase = (await run_contract(db, run))["phase"]
    assert phase["title"] == "Implement"
    failure = phase["hands_on_failure"]
    assert [item["id"] for item in failure["failed"]] == ["S1", "S2"]
    assert failure["failed"][0]["failed_step"]["expected"] == "Last brew"
    assert "Fix the app" in failure["rule"]


def test_a_red_reproduce_check_is_the_expected_result_and_never_reads_as_a_red_hands_on_test():
    """The bug flow's reproduce check uses the same action; red there means the bug is reproduced."""
    run = SimpleNamespace(id="r-1", workflow_key="bug-fix-reproduction", project_id=None, ticket_key="OCX-1", title="T")
    fix = SimpleNamespace(kind="phase", title="Fix", id="fix", config={})
    reproduce = SimpleNamespace(kind="platform_action", title="Reproduce the bug", id="reproduce",
                                config={"action": "hands_on.run", "mode": "reproduce"})
    hands_on = SimpleNamespace(kind="platform_action", title="Hands-on test", id="hands_on",
                               config={"action": "hands_on.run"})

    assert "hands-on test is red" not in continuation_prompts._prompt(run, reproduce, resumed=True, then=fix)
    assert "Phase 'Fix'" in continuation_prompts._prompt(run, hands_on, resumed=True, then=fix)
