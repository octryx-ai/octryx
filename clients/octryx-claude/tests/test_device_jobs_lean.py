from __future__ import annotations

import types
from pathlib import Path

import pytest

from octryx_claude.device_sdk import SdkDriver
from octryx_claude.device_session import PreparedSession
from tests.device_jobs_support import FakeDriver, _manager, _offer, _settle

RUN_PROMPT = "Work one phase of the run."
STORY_PROMPT = "Build one story with your subagents."
PLAIN_PROMPT = "Build the story in the user's message."
PLATFORM_TEXTS = {"system_prompt": RUN_PROMPT, "story_prompt": STORY_PROMPT, "plain_prompt": PLAIN_PROMPT}


def test_a_workflow_run_turn_starts_lean_and_a_chat_turn_does_not():
    from octryx_claude.device_turn_kind import LEAN_TOOLS

    captured = {}
    fake_sdk = types.SimpleNamespace(ClaudeAgentOptions=lambda **kwargs: captured.update(kwargs) or kwargs,
                                     HookMatcher=lambda **kwargs: kwargs)
    lean = PreparedSession(session_key="k", cli_path="claude", settings_path=Path("s.json"), mcp_path=Path("m.json"),
                           env={}, profile="governed", extra={"lean": True, "system_prompt": RUN_PROMPT})
    SdkDriver(sdk=fake_sdk)._options(lean, cwd="/x", resume=None, decide=None)
    assert captured["setting_sources"] == [] and captured["system_prompt"] == RUN_PROMPT
    assert captured["extra_args"]["tools"] == LEAN_TOOLS and "disable-slash-commands" in captured["extra_args"]
    assert captured["settings"] == "s.json"
    captured.clear()
    chat = PreparedSession(session_key="k", cli_path="claude", settings_path=Path("s.json"), mcp_path=Path("m.json"),
                           env={}, profile="governed")
    SdkDriver(sdk=fake_sdk)._options(chat, cwd="/x", resume=None, decide=None)
    assert captured["setting_sources"] == ["user", "project", "local"] and "system_prompt" not in captured
    assert "tools" not in captured["extra_args"]


def test_a_lean_chat_turn_keeps_the_repository_settings_and_a_neutral_prompt():
    from octryx_claude.device_turn_kind import LEAN_CHAT_PROMPT, LEAN_TOOLS

    captured = {}
    fake_sdk = types.SimpleNamespace(ClaudeAgentOptions=lambda **kwargs: captured.update(kwargs) or kwargs,
                                     HookMatcher=lambda **kwargs: kwargs)
    chat = PreparedSession(session_key="k", cli_path="claude", settings_path=Path("s.json"), mcp_path=Path("m.json"),
                           env={}, profile="governed", extra={"lean": True, "workflow_run": False})
    SdkDriver(sdk=fake_sdk)._options(chat, cwd="/x", resume=None, decide=None)
    assert captured["setting_sources"] == ["project"] and captured["system_prompt"] == LEAN_CHAT_PROMPT
    assert captured["extra_args"]["tools"] == LEAN_TOOLS and "TodoWrite" in LEAN_TOOLS
    assert "workflow" not in LEAN_CHAT_PROMPT.lower()


def test_a_run_turn_whose_phase_opted_in_to_subagents_is_a_full_claude_code_story_session():
    from octryx_claude.device_turn_kind import INTERACTIVE_TOOLS, LEAN_CHAT_PROMPT, LEAN_TOOLS

    captured = {}
    fake_sdk = types.SimpleNamespace(ClaudeAgentOptions=lambda **kwargs: captured.update(kwargs) or kwargs,
                                     HookMatcher=lambda **kwargs: kwargs)

    def options(**extra) -> dict:
        captured.clear()
        prepared = PreparedSession(session_key="k", cli_path="claude", settings_path=Path("s.json"),
                                   mcp_path=Path("m.json"), env={}, profile="seat",
                                   extra={"lean": True, **PLATFORM_TEXTS, **extra})
        SdkDriver(sdk=fake_sdk)._options(prepared, cwd="/x", resume=None, decide=None)
        return dict(captured)

    story = options(workflow_run=True, subagents=True)
    assert "tools" not in story["extra_args"] and "disable-slash-commands" in story["extra_args"]
    assert story["system_prompt"] == {"type": "preset", "preset": "claude_code", "append": STORY_PROMPT}
    assert story["disallowed_tools"] == INTERACTIVE_TOOLS and story["setting_sources"] == []
    assert story["settings"] == "s.json"  # the platform's hooks still decide every tool call
    assert story["env"]["CLAUDE_CODE_DISABLE_BACKGROUND_TASKS"] == "1"  # a headless turn never ends with work running
    # No run turn drives the person's Chrome (Claude in Chrome); the browser is the session's own MCP server.
    assert "no-chrome" in story["extra_args"] and "chrome" not in story["extra_args"]
    assert story["mcp_servers"] == "m.json"
    # epic-delivery (runs 1-2): plain Claude Code's settings sources and the platform's plain run note; the
    # platform's hooks still come with the session's flag settings.
    plain = options(workflow_run=True, subagents=True, plain=True)
    assert plain["setting_sources"] == ["user", "project", "local"] and plain["settings"] == "s.json"
    assert plain["system_prompt"]["append"] == PLAIN_PROMPT
    assert plain["thinking"] == {"type": "adaptive", "display": "omitted"}  # as claude -p
    assert "thinking" not in story
    phase = options(workflow_run=True)
    assert phase["extra_args"]["tools"] == LEAN_TOOLS and phase["system_prompt"] == RUN_PROMPT
    # The offer names the run turn's built-in tools and its catalog prompt (both data); a chat turn
    # never takes them over.
    small = options(workflow_run=True, builtin_tools=["Read", "Edit", "Bash"], system_prompt="Fix the bug.")
    assert small["extra_args"]["tools"] == "Read,Edit,Bash" and small["system_prompt"] == "Fix the bug."
    assert options(workflow_run=False, builtin_tools=["Read"])["extra_args"]["tools"] == LEAN_TOOLS
    assert "disallowed_tools" not in phase and "CLAUDE_CODE_DISABLE_BACKGROUND_TASKS" not in phase["env"]
    assert options(workflow_run=True, subagents="true")["extra_args"]["tools"] == LEAN_TOOLS  # only exactly true
    chat = options(workflow_run=False, subagents=True)
    assert chat["extra_args"]["tools"] == LEAN_TOOLS and chat["system_prompt"] == LEAN_CHAT_PROMPT
    # Allow by default, block as an admin option: phase and chat turns have sub-agents and a task list.
    assert LEAN_TOOLS == "Read,Edit,Write,Bash,Grep,Glob,TodoWrite,Agent"
    # The offer's ``web`` adds Claude Code's own WebSearch and WebFetch (they leave from the device).
    research = options(workflow_run=True, web=True)
    assert research["extra_args"]["tools"] == LEAN_TOOLS + ",WebSearch,WebFetch"
    # Claude Code asks before every web call even in acceptEdits; a run has nobody to answer.
    assert research["allowed_tools"] == ["WebSearch", "WebFetch"] and "allowed_tools" not in phase
    # The offer's ``web`` decides, chat turns too; only exactly true.
    web_chat = options(workflow_run=False, web=True)
    assert web_chat["extra_args"]["tools"] == LEAN_TOOLS + ",WebSearch,WebFetch"
    assert web_chat["allowed_tools"] == ["WebSearch", "WebFetch"]
    assert options(workflow_run=True, web=False)["extra_args"]["tools"] == LEAN_TOOLS
    assert options(workflow_run=True, web="true")["extra_args"]["tools"] == LEAN_TOOLS


def test_a_run_turn_without_the_platforms_prompt_text_does_not_start():
    from octryx_claude.device_sdk import DriverStartError

    fake_sdk = types.SimpleNamespace(ClaudeAgentOptions=lambda **kwargs: kwargs, HookMatcher=lambda **kwargs: kwargs)
    for extra in ({"workflow_run": True}, {"workflow_run": True, "subagents": True, "system_prompt": RUN_PROMPT},
                  {"workflow_run": True, "subagents": True, "plain": True, "story_prompt": STORY_PROMPT}):
        prepared = PreparedSession(session_key="k", cli_path="claude", settings_path=Path("s.json"),
                                   mcp_path=Path("m.json"), env={}, profile="seat", extra={"lean": True, **extra})
        with pytest.raises(DriverStartError, match="run_prompt_missing"):
            SdkDriver(sdk=fake_sdk)._options(prepared, cwd="/x", resume=None, decide=None)


@pytest.mark.asyncio
async def test_the_offers_subagents_flag_reaches_the_turn_and_defaults_off(state, tmp_path):
    seen = []

    class Recording(FakeDriver):
        async def run_turn(self, prepared, **kwargs):
            seen.append(dict(prepared.extra))
            return await super().run_turn(prepared, **kwargs)

    manager, _channel, repo = _manager(state, tmp_path, driver=Recording())
    await manager.handle("job_offer", _offer(repo, workflow_run_id="run-1", subagents=True))
    await _settle(manager)
    await manager.handle("job_offer", _offer(repo, job_id="dj_2", turn_id="t2", workflow_run_id="run-1"))
    await _settle(manager)
    assert [(extra["lean"], extra["subagents"]) for extra in seen] == [(True, True), (True, False)]


@pytest.mark.asyncio
async def test_the_offers_tools_prompt_texts_window_and_web_reach_the_turn(state, tmp_path):
    seen = []

    class Recording(FakeDriver):
        async def run_turn(self, prepared, **kwargs):
            seen.append(dict(prepared.extra))
            return await super().run_turn(prepared, **kwargs)

    manager, _channel, repo = _manager(state, tmp_path, driver=Recording())
    await manager.handle("job_offer", _offer(repo, workflow_run_id="run-1", builtin_tools=["Read", "Bash"],
                                             compact_window=150_000, model_context_window=200_000, web=True,
                                             **PLATFORM_TEXTS))
    await _settle(manager)
    extra = seen[0]
    assert extra["builtin_tools"] == ["Read", "Bash"] and extra["compact_window"] == 150_000
    assert extra["model_context_window"] == 200_000
    assert {key: extra[key] for key in PLATFORM_TEXTS} == PLATFORM_TEXTS
    assert extra["web"] is True and "research" not in extra
