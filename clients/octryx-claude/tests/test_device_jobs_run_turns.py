"""Run turns: allow rules, compaction, slots, subagent models, browser server, and clean-up."""

from __future__ import annotations

import asyncio
import json
import types
from pathlib import Path

import pytest

from octryx_claude import device_state, launch_settings, session_hooks
from octryx_claude.device_job_offers import Turn
from octryx_claude.device_sdk import SdkDriver
from octryx_claude.device_session import PreparedSession
from tests.device_jobs_support import FakeDriver, _fake_sdk, _manager, _offer, _settle


def test_the_workspace_autonomy_set_becomes_claude_codes_allow_rules():
    """The allow-set comes from the platform's client policy, next to the deny rules."""

    policy = {"permissions": {"deny": ["Bash(git push --force:*)"], "ask": [],
                              "allow": ["Bash(git commit:*)", "Bash(.venv/bin/python:*)"]}}
    settings = launch_settings.build_settings(shim=Path("/shim"), state_root=Path("/state"), env={}, policy=policy,
                                     base_url="https://octryx.example.test", profile="governed")
    allow = settings["permissions"]["allow"]
    assert "Bash(git commit:*)" in allow and "Bash(.venv/bin/python:*)" in allow
    assert "Bash(git push --force:*)" in settings["permissions"]["deny"]


def test_a_run_turn_on_a_tiered_model_compacts_below_the_price_tier():
    """Claude Code compacts about 33K below its window. A run turn on Haiku compacts at ~92K (window 125K), below its
    100K price tier, a run turn on any other model too; a chat turn keeps the device's window, and a smaller device
    window stays."""
    from octryx_claude.device_turn_kind import run_compact_window

    def prepared(model="", env_model="claude-haiku-5-5", run=True, window=200_000):
        return PreparedSession(session_key="s", cli_path="c", settings_path=Path("/s"), mcp_path=Path("/m"),
                               env={"ANTHROPIC_MODEL": env_model}, profile="seat", model=model,
                               extra={"workflow_run": run, "context_window": window})

    assert run_compact_window(prepared()) == 125_000
    assert run_compact_window(prepared(model="claude-haiku-5-5", env_model="")) == 125_000
    assert run_compact_window(prepared(run=False)) == 200_000
    # A model without a tier (the Sonnet coordinator, window 1M) compacts
    # there too.
    assert run_compact_window(prepared(env_model="claude-sonnet-5-5")) == 125_000
    assert run_compact_window(prepared(env_model="claude-sonnet-5-5", window=1_000_000)) == 125_000
    assert run_compact_window(prepared(env_model="claude-sonnet-5-5", run=False, window=1_000_000)) == 1_000_000
    assert run_compact_window(prepared(window=110_000)) == 110_000
    assert run_compact_window(prepared(window=0)) == 125_000
    # The story session (a run turn whose phase opted in to subagents) keeps the device's window.
    story = prepared()
    story.extra["subagents"] = True
    assert run_compact_window(story) == 200_000
    sdk = _fake_sdk()
    options = SdkDriver(sdk)._options(prepared(), cwd="/x", resume="cs-1", decide=None)
    assert options.env["CLAUDE_CODE_AUTO_COMPACT_WINDOW"] == "125000"
    # The run class's cap only lowers it; Claude Code compacts there itself.
    capped = prepared(env_model="claude-sonnet-5-5", window=1_000_000)
    capped.extra["compact_window"] = 110_000
    assert run_compact_window(capped) == 110_000
    capped.extra["compact_window"] = 200_000
    assert run_compact_window(capped) == 125_000
    story.extra["compact_window"] = 150_000
    assert run_compact_window(story) == 150_000


@pytest.mark.asyncio
async def test_a_teams_platform_turn_takes_no_slot_and_items_fill_every_slot(state, tmp_path):
    """With four parallel items the run's main thread (its git work, the
    coordinator) took a slot, so only three items ran. A turn the platform marks ``slot_exempt`` for a workflow run is
    counted only among such turns; an offer without a run cannot claim it."""
    hold = asyncio.Event()
    manager, channel, repo = _manager(state, tmp_path, driver=[FakeDriver(hold=hold) for _ in range(4)], parallel=2)
    for index in (1, 2):
        await manager.handle("job_offer", _offer(repo, job_id=f"dj_{index}", turn_id=f"t{index}",
                                                 workflow_run_id="00000000-0000-4000-8000-000000000001"))
    await manager.handle("job_offer", _offer(repo, job_id="dj_git", turn_id="t3", slot_exempt=True,
                                             workflow_run_id="00000000-0000-4000-8000-000000000001"))
    await manager.handle("job_offer", _offer(repo, job_id="dj_x", turn_id="t4", slot_exempt=True))
    await asyncio.sleep(0.05)
    assert set(manager.turns) == {"dj_1", "dj_2", "dj_git"}
    assert channel.of("job_rejected") == [{"turn_id": "t4", "reason": "device_busy"}]
    hold.set()
    await _settle(manager)


def test_the_default_parallel_limit_lets_a_team_run_side_by_side():
    assert device_state.DEFAULT_PARALLEL_JOBS == 6


def test_a_run_turns_subagents_work_on_the_turns_model():
    """The sub-agents of a run turn work on the turn's model, not the device's "main" alias. The value goes into the
    session's settings env, which
    outranks the child's environment; a chat turn keeps the device's aliases."""
    from octryx_claude.device_session import subagents_follow_the_turn

    aliases = {"ANTHROPIC_MODEL": "claude-opus-5-5", "CLAUDE_CODE_SUBAGENT_MODEL": "claude-opus-5-5"}
    run = subagents_follow_the_turn(aliases, model="claude-haiku-5-5", workflow_run="run-1")
    assert run["CLAUDE_CODE_SUBAGENT_MODEL"] == "claude-haiku-5-5" and run["ANTHROPIC_MODEL"] == "claude-opus-5-5"
    assert subagents_follow_the_turn(aliases, model="claude-haiku-5-5", workflow_run="") == aliases
    assert subagents_follow_the_turn(aliases, model="", workflow_run="run-1") == aliases


def test_only_a_run_turn_with_a_browser_gets_the_playwright_server_in_its_mcp_config(tmp_path):
    """The browser MCP server instead of ``--chrome``; every run turn whose
    phase opted in (the job manager describes the server only then), a story session or a phase turn."""
    captured = {}
    fake_sdk = types.SimpleNamespace(ClaudeAgentOptions=lambda **kwargs: captured.update(kwargs) or kwargs,
                                     HookMatcher=lambda **kwargs: kwargs)
    session_mcp = tmp_path / "mcp.json"
    session_mcp.write_text(json.dumps({"mcpServers": {"octryx-knowledge": {"type": "http", "url": "u"}}}))
    spec = {"type": "stdio", "command": "node", "args": ["cli.js", "--isolated", "--headless"]}

    def mcp(**extra) -> str:
        captured.clear()
        prepared = PreparedSession(session_key="k", cli_path="claude", settings_path=Path("s.json"),
                                   mcp_path=session_mcp, env={}, profile="seat",
                                   extra={"lean": True, "system_prompt": "Phase.", "story_prompt": "Story.", **extra})
        SdkDriver(sdk=fake_sdk)._options(prepared, cwd="/x", resume=None, decide=None)
        return captured["mcp_servers"]

    browsing = mcp(workflow_run=True, subagents=True, browser_mcp=spec)
    assert browsing != str(session_mcp)
    assert json.loads(Path(browsing).read_text())["mcpServers"]["playwright"] == spec
    assert mcp(workflow_run=True, subagents=True) == str(session_mcp)  # no browser installed: none
    assert json.loads(Path(mcp(workflow_run=True, browser_mcp=spec)).read_text())["mcpServers"]["playwright"] == spec
    assert mcp(workflow_run=True) == str(session_mcp)  # a phase that did not opt in: no browser
    assert mcp(workflow_run=False, browser_mcp=spec) == str(session_mcp)  # a chat turn never gets one


@pytest.mark.asyncio
async def test_a_run_turn_marks_its_processes_and_stops_what_still_listens(state, tmp_path, monkeypatch):
    """App servers a session started stop with its turn."""
    from octryx_claude import run_wip, turn_processes

    stopped: list[str] = []
    monkeypatch.setattr(turn_processes, "stop_leftovers", lambda mark, **_kw: stopped.append(mark) or [4242])
    monkeypatch.setattr(run_wip, "push_run_wip", lambda *args: {"state": "unchanged"})
    driver = FakeDriver()
    manager, _channel, repo = _manager(state, tmp_path, driver=driver)
    await manager.handle("job_offer", _offer(repo, workflow_run_id="run-1"))
    await _settle(manager)
    mark = driver.calls[0]["env"][turn_processes.MARK_ENV]
    assert len(mark) == 32 and stopped == [mark]
    await manager.handle("job_offer", _offer(repo, job_id="dj_2", turn_id="t2"))  # a chat turn: nothing stopped
    await _settle(manager)
    assert turn_processes.MARK_ENV not in driver.calls[1]["env"] and stopped == [mark]


@pytest.mark.asyncio
async def test_the_next_turn_waits_for_the_last_turns_clean_up_instead_of_busy(state, tmp_path):
    """A turn offered while the device still cleans up after ``turn_finished`` waits for that clean-up instead of
    being refused ``device_job_busy``."""
    manager, channel, repo = _manager(state, tmp_path)
    turn = Turn("dj_1", "t0", limits={})
    turn.finished = True

    async def cleaning_up():
        await asyncio.sleep(0.2)
        manager.turns.pop("dj_1", None)

    turn.task = asyncio.create_task(cleaning_up())
    manager.turns["dj_1"] = turn
    await manager._offer(_offer(repo, turn_id="t1"))
    assert channel.of("job_rejected") == []  # accepted once the clean-up was over
    await _settle(manager)

    busy = Turn("dj_2", "t2", limits={})  # still working: refused
    busy.task = asyncio.create_task(asyncio.sleep(5))
    manager.turns["dj_2"] = busy
    await manager._offer(_offer(repo, job_id="dj_2", turn_id="t3"))
    assert [body["reason"] for body in channel.of("job_rejected")] == ["device_job_busy"]
    busy.task.cancel()


def test_a_compaction_is_reported_as_the_runs_event(state, monkeypatch):
    """PreCompact and PostCompact go to the platform as the run's ``session_compacted``."""
    from octryx_claude import hooks

    sent = []
    monkeypatch.setattr(hooks.SessionContext, "from_env", staticmethod(lambda: object()))
    monkeypatch.setattr("octryx_claude.session_hooks.call_control_plane",
                        lambda *args, **kwargs: sent.append((args[3], kwargs["body"])))
    session_hooks._report_compaction(state, {"trigger": "auto"}, "pre", http=None)
    session_hooks._report_compaction(state, {"trigger": "auto", "compact_summary": "abc"}, "post", http=None)
    assert sent == [("/sessions/compaction", {"stage": "pre", "trigger": "auto"}),
                    ("/sessions/compaction", {"stage": "post", "trigger": "auto", "summary_chars": 3})]
