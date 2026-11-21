"""The device job manager and SDK driver: local re-checks on every offer, nothing but the prompt and its
target taken from the platform, approvals that deny on timeout, stop, and parallel turns. Fakes only."""

from __future__ import annotations

import asyncio

import pytest

from octryx_claude import device_state
from octryx_claude.state import write_private_json
from tests.device_jobs_support import FakeDriver, Prepare, _manager, _offer, _settle


@pytest.mark.asyncio
async def test_an_offer_runs_as_a_session_and_ignores_everything_but_prompt_and_target(state, tmp_path):
    driver, prepare = FakeDriver(), Prepare()
    manager, channel, repo = _manager(state, tmp_path, driver=driver, prepare=prepare)
    crafted = _offer(repo, settings={"permissions": {"allow": ["Bash(*)"]}}, permission_mode="bypassPermissions",
                     mcp_servers={"evil": {}}, allow=["Bash"], resume_session_id="cs-0")
    await manager.handle("job_offer", crafted)
    await _settle(manager)
    assert [kind for _job, kind, _body in channel.sent] == ["job_accepted", "job_event", "turn_finished"]
    assert set(prepare.calls[0]) == {"base_url", "workspace_id", "profile", "folder", "model", "http", "shim",
                                     "workflow_run", "job_id"}
    assert prepare.calls[0]["job_id"] == "dj_1"  # the platform binds the thread's own session by its job
    assert prepare.calls[0]["workflow_run"] == ""  # the thread follows no workflow run
    assert prepare.calls[0]["model"] == ""  # no model in the offer: the device's default
    assert prepare.calls[0]["profile"] == "governed" and prepare.calls[0]["workspace_id"] == "ws-1"
    assert prepare.calls[0]["folder"] == str(repo.resolve())  # the checked realpath binds the repository
    assert driver.calls[0]["cwd"] == str(repo.resolve()) and driver.calls[0]["resume"] == "cs-0"
    assert channel.of("turn_finished")[0]["status"] == "success" and prepare.closed == 1
    assert device_state.read_status(state)["running_jobs"] == 0

    await manager.handle("job_offer", crafted)  # the same turn again (a redelivery): ignored
    await _settle(manager)
    assert len(channel.of("job_accepted")) == 1 and channel.of("job_rejected") == []


@pytest.mark.asyncio
async def test_a_turn_an_earlier_process_saw_but_never_ran_is_handed_back(state, tmp_path):
    """A service restarted between the offer and its acceptance finds the turn in its seen list: it hands the turn
    back (``device_restarted``) instead of ignoring the redelivery, and the platform offers it once more."""
    from octryx_claude.device_jobs import SEEN_FILE

    write_private_json(state.ensure().root / SEEN_FILE, {"turns": ["t-lost"]})
    manager, channel, repo = _manager(state, tmp_path)
    await manager.handle("job_offer", _offer(repo, job_id="dj_9", turn_id="t-lost"))
    await _settle(manager)
    assert channel.of("job_rejected") == [{"turn_id": "t-lost", "reason": "device_restarted"}]
    assert channel.of("job_accepted") == []


@pytest.mark.asyncio
async def test_local_rechecks_reject_with_fixed_codes(state, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    manager, channel, repo = _manager(state, tmp_path)
    (repo / "escape").symlink_to(outside)
    await manager.handle("job_offer", _offer(repo / "escape", turn_id="t1"))
    await manager.handle("job_offer", _offer(outside, turn_id="t2"))
    await manager.handle("job_offer", _offer(repo, turn_id="t3", profile="seat"))
    await manager.handle("job_offer", _offer(repo, turn_id="t4", profile="root"))
    channel.paused = True
    await manager.handle("job_offer", _offer(repo, turn_id="t5"))
    assert [body["reason"] for body in channel.of("job_rejected")] == [
        "folder_not_allowlisted_on_device", "folder_not_allowlisted_on_device", "profile_unavailable_on_device",
        "profile_unavailable_on_device", "device_paused"]

    refused, refused_channel, repo2 = _manager(state, tmp_path, prepare=Prepare(refuse="seat_mode_forbidden"))
    await refused.handle("job_offer", _offer(repo2, turn_id="t6"))
    await _settle(refused)
    assert refused_channel.of("job_rejected") == [{"turn_id": "t6", "reason": "seat_mode_forbidden"}]


@pytest.mark.asyncio
async def test_parallel_turns_up_to_the_device_limit(state, tmp_path):
    hold = asyncio.Event()
    drivers = [FakeDriver(hold=hold), FakeDriver(hold=hold)]
    manager, channel, repo = _manager(state, tmp_path, driver=drivers, parallel=2)
    await manager.handle("job_offer", _offer(repo, job_id="dj_1", turn_id="t1"))
    await manager.handle("job_offer", _offer(repo, job_id="dj_2", turn_id="t2"))
    await manager.handle("job_offer", _offer(repo, job_id="dj_3", turn_id="t3"))
    await asyncio.sleep(0.05)
    assert len(manager.turns) == 2 and device_state.read_status(state)["running_jobs"] == 2
    assert channel.of("job_rejected") == [{"turn_id": "t3", "reason": "device_busy"}]
    hold.set()
    await _settle(manager)
    assert len(channel.of("turn_finished")) == 2


@pytest.mark.asyncio
async def test_approvals_follow_the_owner_decision_and_deny_on_timeout(state, tmp_path):
    driver = FakeDriver(tools=[("Edit", {"file_path": "a.py"}), ("Bash", {"command": "make"}),
                               ("AskUserQuestion", {}), ("Bash", {"command": "rm -rf build"})])
    manager, channel, repo = _manager(state, tmp_path, driver=driver)
    await manager.handle("job_offer", _offer(repo))
    for expected_decision in ("allowed_job_edits", "allowed"):
        for _ in range(100):
            requests = channel.of("approval_request")
            if len(requests) > len([v for v in driver.verdicts if v]) and not any(
                    entry[1].done() for entry in manager._approvals.values()):
                break
            await asyncio.sleep(0.01)
        request = channel.of("approval_request")[-1]
        await manager.handle("approval_decision", {"job_id": "dj_other", "approval_id": request["approval_id"],
                                                   "decision": "allowed"})  # another job's id: ignored
        await manager.handle("approval_decision", {"job_id": "dj_1", "approval_id": request["approval_id"],
                                                   "decision": expected_decision})
    await _settle(manager)
    assert driver.verdicts[0] == ("allow_job_edits", "")
    assert driver.verdicts[1] == ("allow", "")
    assert driver.verdicts[2][0] == "deny" and len(channel.of("approval_request")) == 3  # no card for questions
    assert driver.verdicts[3] == ("deny", "No decision within 1 min; denied.")
    assert channel.of("approval_resolved")[0]["outcome"] == "timed_out"
    assert channel.of("approval_request")[0]["input_preview"] == "a.py"


@pytest.mark.asyncio
async def test_stop_and_pause_interrupt_running_turns(state, tmp_path):
    hold = asyncio.Event()
    driver = FakeDriver(hold=hold)
    manager, channel, repo = _manager(state, tmp_path, driver=driver)
    await manager.handle("job_offer", _offer(repo))
    await asyncio.sleep(0.05)
    await manager.handle("cancel", {"job_id": "dj_1", "turn_id": "t1"})
    await _settle(manager)
    assert driver.interrupted and channel.of("turn_finished")[0]["status"] == "stopped"

    driver2 = FakeDriver(hold=asyncio.Event())
    manager2, channel2, repo2 = _manager(state, tmp_path, driver=driver2)
    await manager2.handle("job_offer", _offer(repo2, turn_id="t9"))
    await asyncio.sleep(0.05)
    await manager2.handle("pause", {})
    await _settle(manager2)
    assert channel2.of("turn_finished")[0]["status"] == "paused"
