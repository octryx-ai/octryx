"""One story session per story: the platform keeps branch, tests, review, push and pull request around it; a red
pipeline and a high finding go back into the same session."""

from __future__ import annotations

import copy
import json

import pytest

from app.models import WorkflowRun
from app.services.devices.job_events import apply_event
from app.services.devices.job_offer import offer_body
from app.services.workflow_runs.epic_chain import STORY_WORKFLOW
from app.services.workflow_runs.octryx.continuation_marker import CONTEXT_KEY
from app.services.workflow_runs.octryx.subagents import run_allows_subagents
from app.services.workflow_runs.platform.pr_details import review_notes_text
from app.services.workflow_runs.run_start import startable_workflows_for
from tests.epic_delivery_story_session_support import STORY, _seed
from tests.scripted_pool_support import scripted_pool  # noqa: F401 - fixture
from tests.workflow_run_octryx_continuation_support import _confirm, _device_run, _jobs, _reenter

pytestmark = pytest.mark.usefixtures("scripted_pool")


def test_epic_delivery_is_the_default_for_an_epics_stories():
    assert STORY_WORKFLOW == "epic-delivery"
    stories = next(node for node in _seed("spec-writing")["definition"]["nodes"] if node["id"] == "stories")
    assert stories["config"]["params"]["story_workflow"] == "epic-delivery"
    split = next(node for node in _seed("spec-writing")["definition"]["nodes"] if node["id"] == "split")
    assert "coordinator splits it into work items" not in split["config"]["workflow_contract"]["when_to_use"]


@pytest.mark.asyncio
async def test_an_installation_offers_the_story_workflows(db):
    from app.services.workflow_runs.seeding import seed_phased_workflows
    from tests.phased_workflow_fixtures import admin_user

    await seed_phased_workflows(db, admin_user=await admin_user(db))
    keys = {item["key"] for item in await startable_workflows_for(db, project_id=None)}
    assert {"spec-writing", "team-delivery", "epic-delivery"} <= keys


@pytest.mark.asyncio
async def test_a_red_pipeline_goes_back_into_the_same_story_session_with_its_subagents(db):
    admin, _device, thread, run = await _device_run(db, definition=STORY)
    await _confirm(db, run, admin)
    [job] = await _jobs(db, thread)
    assert await run_allows_subagents(db, run)
    await apply_event(db, job, "job_event", {"kind": "session", "claude_session_id": "claude-story-1"}, limits={})
    await apply_event(db, job, "job_accepted", {"turn_id": job.turn_id}, limits={})

    await _reenter(db, run, "pipeline", runtime_step=True)
    assert run.context[CONTEXT_KEY]["then_phase"] == "work"
    await apply_event(db, job, "turn_finished", {"turn_id": job.turn_id, "status": "success"}, limits={})
    assert job.status == "offered" and offer_body(job, limits={})["resume_session_id"] == "claude-story-1"
    assert "pipeline ran" in job.turn_prompt and "pipeline_failure" in job.turn_prompt
    assert "do not re-read" in job.turn_prompt
    assert await run_allows_subagents(db, run)

    await apply_event(db, job, "job_accepted", {"turn_id": job.turn_id}, limits={})
    await _reenter(db, run, "work")
    marker = run.context[CONTEXT_KEY]
    assert (marker["node_id"], marker["state"], marker["phase"]) == ("work", "started", True)
    assert len(await _jobs(db, thread)) == 1


@pytest.mark.asyncio
async def test_a_green_pipeline_of_a_phase_without_subagents_keeps_the_lean_turn(db):
    definition = copy.deepcopy(STORY)
    del next(node for node in definition["nodes"] if node["id"] == "work")["config"]["subagents"]
    admin, _device, thread, run = await _device_run(db, definition=definition)
    await _confirm(db, run, admin)
    await _reenter(db, run, "pipeline", runtime_step=True)
    assert not await run_allows_subagents(db, run)


def test_medium_and_low_findings_become_notes_on_the_pull_request():
    run = WorkflowRun(context={"review_notes": [
        {"severity": "medium", "file": "src/app.py", "line": 12, "fix": "Validate the  calorie range."},
        {"severity": "low", "file": "", "fix": "Name the helper after what it returns."}]})
    text = review_notes_text(run)
    assert text.startswith("Review notes (medium and low findings")
    assert "- medium (src/app.py:12): Validate the calorie range." in text
    assert "- low: Name the helper after what it returns." in text
    assert review_notes_text(WorkflowRun(context={})) == ""


def test_a_session_browser_is_its_own_and_checks_both_widths():
    from app.services.workflow_runs.octryx.browser import BROWSER_NOTE

    assert "browser_resize 1280x800" in BROWSER_NOTE["rule"] and "390x844" in BROWSER_NOTE["rule"]
    assert "claude-in-chrome" not in json.dumps(BROWSER_NOTE)
    from app.models import DeviceJob

    offer = offer_body(DeviceJob(id="j", profile="seat", folder="/f"), limits={}, browser=True)
    assert offer["browser"] is True and "chrome" not in offer


@pytest.mark.asyncio
async def test_the_offer_carries_the_browser_flag_of_the_phase_the_turn_works(db):
    from app.services.workflow_runs.octryx.browser import node_allows_browser
    from app.services.workflow_runs.octryx.subagents import turn_phase

    definition = copy.deepcopy(STORY)
    next(node for node in definition["nodes"] if node["id"] == "work")["config"]["browser"] = True
    admin, _device, thread, run = await _device_run(db, definition=definition)
    await _confirm(db, run, admin)
    assert node_allows_browser(await turn_phase(db, run))
    await _reenter(db, run, "pipeline", runtime_step=True)
    assert node_allows_browser(await turn_phase(db, run))
    assert not node_allows_browser(await turn_phase(db, None))


def test_the_workspaces_browser_phases_are_validated():
    from app.services.devices.device_runs_keys import DEFAULTS, DeviceRunsPolicyError, normalize_device_runs

    assert DEFAULTS["browser_phases"] == []
    assert normalize_device_runs({"browser_phases": [" epic-delivery.implement ", "epic-delivery.implement",
                                                     "epic-delivery.independent_review"]}, "p") == \
        {"browser_phases": ["epic-delivery.implement", "epic-delivery.independent_review"]}
    for bad in ("epic-delivery", [""], ["implement"], ["epic-delivery."], ["epic delivery.implement"], [3],
                [f"w.{'n' * 120}"], [f"w.n{index}" for index in range(21)]):
        with pytest.raises(DeviceRunsPolicyError) as refused:
            normalize_device_runs({"browser_phases": bad}, "p")
        assert (refused.value.reason, refused.value.path) == ("invalid_browser_phases", "p.browser_phases")


@pytest.mark.asyncio
async def test_a_workspace_switches_the_browser_on_for_its_listed_phase_in_the_offer_and_the_contract(db):
    from app.services.devices.jobs_channel import _thread_run
    from app.services.workflow_runs.octryx.contract import run_contract
    from tests.devices.device_support import enable_device_runs

    definition = copy.deepcopy(STORY)
    next(node for node in definition["nodes"] if node["id"] == "work")["config"]["browser"] = False
    admin, _device, thread, run = await _device_run(db, definition=definition)

    async def browser() -> tuple[bool, bool]:
        [job] = await _jobs(db, thread)
        phase = (await run_contract(db, run))["phase"]
        return (await _thread_run(db, job))["browser"], "browser" in phase

    await _confirm(db, run, admin)
    assert run.current_node_id == "work" and await browser() == (False, False)
    for listed in (["other-workflow.work"], [f"{run.workflow_key}.other_phase"]):
        await enable_device_runs(db, browser_phases=listed)
        assert await browser() == (False, False)
    await enable_device_runs(db, browser_phases=[f"{run.workflow_key}.work"])
    assert await browser() == (True, True)
    from app.services.workflow_runs.octryx.browser import phase_allows_browser

    assert await phase_allows_browser(db, run, None) is False


@pytest.mark.asyncio
async def test_a_node_with_browser_true_keeps_it_without_any_workspace_list(db):
    from app.services.workflow_runs.octryx.browser import phase_allows_browser
    from app.services.workflow_runs.octryx.contract import run_contract

    definition = copy.deepcopy(STORY)
    next(node for node in definition["nodes"] if node["id"] == "work")["config"]["browser"] = True
    admin, _device, _thread, run = await _device_run(db, definition=definition)
    await _confirm(db, run, admin)
    from app.services.workflow_runs.octryx.subagents import turn_phase

    assert await phase_allows_browser(db, run, await turn_phase(db, run)) is True
    assert "browser" in (await run_contract(db, run))["phase"]
