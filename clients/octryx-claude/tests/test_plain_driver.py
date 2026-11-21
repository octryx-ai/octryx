"""epic-delivery runs its story session as ``claude -p``: a same-hour plain control built a story in 9:28,
the Agent SDK session in 20-30 min. The command must be plain Claude Code's plus the platform's settings file."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from octryx_claude import plain_session
from octryx_claude.plain_driver import PlainCliDriver, runs_plain
from octryx_claude.plain_session import command, environment, map_line
from tests.plain_driver_support import _prepared


def test_the_turn_is_claude_p_with_the_platforms_settings_and_nothing_of_the_sdk(tmp_path):
    prepared = _prepared(tmp_path)
    args = command(prepared, resume=None)
    assert args[:2] == ["claude", "-p"] and "--include-partial-messages" not in args
    assert args[args.index("--output-format") + 1] == "json"  # the only form that omits thinking text
    assert args[args.index("--settings") + 1].endswith("settings.json")  # hooks: the hard-deny list on the device
    assert args[args.index("--permission-mode") + 1] == "bypassPermissions"
    assert args[args.index("--session-id") + 1] == prepared.session_key and "--resume" not in args
    assert "--resume" in command(prepared, resume="cs-1")  # the next story continues the session
    env = environment(prepared)
    assert "CLAUDE_CODE_DISABLE_BACKGROUND_TASKS" not in env  # background subagents, as in plain Claude Code
    # Compacts where plain claude -p does (the model's own window), not at the device's 200K.
    assert "CLAUDE_CODE_AUTO_COMPACT_WINDOW" not in env
    prepared.env["CLAUDE_CODE_AUTO_COMPACT_WINDOW"] = "200000"
    assert "CLAUDE_CODE_AUTO_COMPACT_WINDOW" not in environment(prepared)
    del prepared.env["CLAUDE_CODE_AUTO_COMPACT_WINDOW"]
    # A seat session sends Claude Code's own request shape (betas, thinking display omitted, clear_thinking).
    from octryx_claude.plain_session import own_request_shape

    prepared.env["CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS"] = "1"
    assert "CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS" not in environment(prepared)
    prepared.settings_path.write_text(json.dumps({"env": {"CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS": "1", "A": "b"}}))
    own_request_shape(prepared)
    assert json.loads(prepared.settings_path.read_text())["env"] == {"A": "b"}
    assert runs_plain(prepared) and not runs_plain(_prepared(tmp_path, permission_mode="default"))
    assert not runs_plain(_prepared(tmp_path, plain=False))


def test_the_prompt_goes_in_on_stdin_and_never_into_the_process_list(tmp_path):
    """A subagent's ``pkill -f "tinytasks.run --port 0"`` stopped every session whose argv carried the story (live
    Token-gap mini test): the story names the app's command line."""
    fake = tmp_path / "claude"
    fake.write_text('#!/bin/sh\necho "$@" > "$0.argv"\ncat > "$0.stdin"\n'
                    'echo \'{"type": "result", "is_error": false, "result": "ok", "session_id": "cs-1"}\'\n')
    fake.chmod(0o755)
    story = "Build this story.\n\n`python -m tinytasks.run --port 0` serves /"

    async def emit(event):
        return None

    result = asyncio.run(PlainCliDriver().run_turn(_prepared(tmp_path, cli=str(fake)), cwd=str(tmp_path),
                                                   prompt=story, resume=None, emit=emit))
    assert result["status"] == "success"
    assert (tmp_path / "claude.stdin").read_text() == story
    argv = (tmp_path / "claude.argv").read_text()
    assert "tinytasks" not in argv and argv.startswith("-p ")


def test_the_run_note_names_the_one_screenshot_form_that_leaves_the_sandbox(tmp_path):
    """Own Playwright scripts cannot start Chromium in the sandbox (run 5b: 21 sandbox refusals, a frontend told to
    "verify by careful reading"); the note names the wrapped CLI form up front."""
    from octryx_claude import local_tests
    from octryx_claude.plain_session import PLAIN_NOTE

    assert "python -m playwright screenshot --viewport-size 1280,800" in PLAIN_NOTE
    example = "python -m playwright screenshot --viewport-size 1280,800 http://127.0.0.1:8765/ shots/home.png"
    assert local_tests.is_test_run(example, "/repo")


def test_the_json_result_is_the_turns_result(tmp_path):
    line = {"type": "result", "subtype": "success", "is_error": False, "result": "Done", "session_id": "cs-9",
            "total_cost_usd": 0.5, "usage": {"output_tokens": 3}}
    fake = tmp_path / "claude"
    fake.write_text("#!/bin/sh\ncat <<'EOF'\n" + json.dumps(line) + "\nEOF\n")
    fake.chmod(0o755)
    events = []

    async def emit(event):
        events.append(event)

    result = asyncio.run(PlainCliDriver().run_turn(_prepared(tmp_path, cli=str(fake)), cwd=str(tmp_path),
                                                   prompt="x", resume=None, emit=emit))
    assert (result["status"], result["claude_session_id"], result["cost_usd"]) == ("success", "cs-9", 0.5)
    assert [event["kind"] for event in events][-2:] == ["session", "text"]
    assert events[0] == {"kind": "session", "claude_session_id": "00000000-0000-4000-8000-0000000000dd"}  # heartbeat
    assert map_line({"type": "system", "subtype": "compact_boundary",
                     "compact_metadata": {"trigger": "auto", "pre_tokens": 9}})[0]["kind"] == "compaction"


def test_the_run_note_starts_backend_frontend_and_system_tests_as_three_parallel_subagents():
    """The run note starts backend, frontend and system tests as three parallel subagents."""
    from octryx_claude.plain_session import PLAIN_NOTE

    # Prompt audit (#8): the three in parallel where the story has them, never a forced backend agent on a
    # frontend-only story.
    assert "backend, frontend and system tests where the story has them, in one message so they run in parallel" \
        in PLAIN_NOTE


def test_the_frontend_subagent_owns_the_screen_look_and_the_lead_runs_the_suite_once():
    """The frontend subagent owns the screen look; the lead runs the declared suite once."""
    from octryx_claude.plain_session import PLAIN_NOTE

    assert "The frontend subagent owns the look at the screens" in PLAIN_NOTE
    assert "you do not read screenshots yourself" in PLAIN_NOTE
    assert "Run the declared test commands once at the end, and again only after a change" in PLAIN_NOTE


def test_a_subagent_named_sonnet_or_opus_runs_on_the_phases_model(tmp_path):
    """A subagent started with model "sonnet" or "opus" runs on the phase's model, never escalated to Opus."""
    from octryx_claude.plain_session import PLAIN_NOTE, SUBAGENT_ALIAS_ENV

    seen = tmp_path / "seen.json"
    fake = tmp_path / "claude"
    fake.write_text("#!/bin/sh\n"
                    f"cp \"$4\" {seen}.settings 2>/dev/null; env > {seen}.env\n"
                    "cat > /dev/null\necho '{\"type\": \"result\", \"is_error\": false, \"result\": \"ok\"}'\n")
    fake.chmod(0o755)
    prepared = _prepared(tmp_path, cli=str(fake))
    prepared.settings_path.write_text(json.dumps({"env": {
        "ANTHROPIC_MODEL": "claude-opus-5-5", "ANTHROPIC_DEFAULT_SONNET_MODEL": "claude-opus-5-5",
        "ANTHROPIC_DEFAULT_OPUS_MODEL": "claude-opus-5-5", "ANTHROPIC_DEFAULT_HAIKU_MODEL": "claude-sonnet-5",
        "CLAUDE_CODE_SUBAGENT_MODEL": "claude-haiku-5-5", "X": "kept"}}))

    async def emit(event):
        return None

    asyncio.run(PlainCliDriver().run_turn(prepared, cwd=str(tmp_path), prompt="S1", resume=None, emit=emit))
    env = json.loads(prepared.settings_path.read_text())["env"]
    assert {key: env[key] for key in SUBAGENT_ALIAS_ENV} == {key: "claude-haiku-5-5" for key in SUBAGENT_ALIAS_ENV}
    assert env["X"] == "kept"  # everything else in the platform's settings stays
    process_env = dict(line.split("=", 1) for line in seen.with_suffix(".json.env").read_text().splitlines()
                       if "=" in line)
    assert all(process_env[key] == "claude-haiku-5-5" for key in SUBAGENT_ALIAS_ENV)
    assert "without a model parameter" in PLAIN_NOTE


def test_a_session_without_a_phase_model_keeps_its_settings(tmp_path):
    from octryx_claude.plain_session import pin_subagent_models

    prepared = _prepared(tmp_path)
    prepared.model = ""
    prepared.settings_path.write_text(json.dumps({"env": {"ANTHROPIC_DEFAULT_SONNET_MODEL": "claude-opus-5-5"}}))
    pin_subagent_models(prepared)
    assert json.loads(prepared.settings_path.read_text())["env"]["ANTHROPIC_DEFAULT_SONNET_MODEL"] == "claude-opus-5-5"


def test_a_story_whose_phase_opted_in_gets_its_own_browser_in_this_turns_mcp_config_only(tmp_path):
    """Epic-delivery's plain story session gets the phase's browser too."""
    (tmp_path / "mcp.json").write_text(json.dumps({"mcpServers": {"octryx-knowledge": {"type": "http"}}}))
    plain = command(_prepared(tmp_path), resume=None)
    assert plain[plain.index("--mcp-config") + 1] == str(tmp_path / "mcp.json")  # not opted in: unchanged
    spec = {"type": "stdio", "command": "node", "args": ["cli.js", "--headless"]}
    args = command(_prepared(tmp_path, browser_mcp=spec), resume=None)
    config = json.loads(Path(args[args.index("--mcp-config") + 1]).read_text())["mcpServers"]
    assert config["playwright"] == spec and "octryx-knowledge" in config and "--strict-mcp-config" in args
    assert "playwright" not in json.loads((tmp_path / "mcp.json").read_text())["mcpServers"]


def test_a_phase_with_a_browser_names_the_browser_tools_not_the_screenshot_command():

    assert "python -m playwright screenshot" not in plain_session.PLAIN_NOTE_BROWSER
    assert "mcp__playwright__browser_" in plain_session.PLAIN_NOTE_BROWSER
    assert plain_session.PLAIN_NOTE_BROWSER != plain_session.PLAIN_NOTE


def test_claude_codes_own_rate_limit_error_is_the_turns_error_code(tmp_path):
    """Coordinator: Claude Code's ``error`` of the turn, never the text, marks the seat's limit."""
    rows = [{"type": "assistant", "error": "rate_limit", "message": {"content": []}},
            {"type": "result", "subtype": "success", "is_error": True, "result": "You've hit your session limit",
             "session_id": "cs-1"}]
    fake = tmp_path / "claude"
    fake.write_text("#!/bin/sh\ncat <<'EOF'\n" + json.dumps(rows) + "\nEOF\n")
    fake.chmod(0o755)

    async def emit(_event):
        return None

    result = asyncio.run(PlainCliDriver().run_turn(_prepared(tmp_path, cli=str(fake)), cwd=str(tmp_path),
                                                   prompt="x", resume=None, emit=emit))
    assert (result["status"], result["error"]) == ("error", "rate_limit")
