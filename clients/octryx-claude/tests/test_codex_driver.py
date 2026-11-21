"""Codex as the second engine: a device turn on ``codex exec --json``.

- the session's ``CODEX_HOME`` names only the platform's Responses gateway, with the launcher's token command and no
  key; credentials of the person's shell never reach Codex;
- the same hooks, the PreToolUse one failing closed; a patch is decided per file and one denied file denies it;
- ``ask`` becomes a deny under Codex (it cannot ask);
- Codex's JSON lines become the chat's job events; the thread id is the session the next turn resumes.
"""

from __future__ import annotations

import asyncio
import json
import tomllib

import pytest

from octryx_claude import codex_config, codex_driver, contract_change, launch_settings
from tests.codex_driver_support import _fake_codex, _prepared


def test_codex_home_names_only_the_platform_gateway_and_no_key(tmp_path):
    prepared = _prepared(tmp_path, OPENAI_API_KEY="sk-from-the-shell")
    home = codex_driver.prepare_home(prepared, sandboxed=False)
    config = tomllib.loads((home / "config.toml").read_text())
    provider = config["model_providers"]["octryx"]
    assert config["model_provider"] == "octryx" and config["model"] == "team-coder"
    assert provider["base_url"] == "https://platform.test/api/v1/model-gateway/openai/v1"
    assert provider["wire_api"] == "responses"
    wrapper = str(home / codex_config.ENV_WRAPPER)
    assert provider["auth"]["command"] == wrapper and provider["auth"]["args"] == ["api-key-helper"]
    assert provider["http_headers"]["X-Octryx-Workspace"] == "w1"
    assert provider["http_headers"]["X-Octryx-Workflow-Run"] == "run-1"
    assert config["cli_auth_credentials_store"] == "ephemeral" and config["approval_policy"] == "never"
    assert config["web_search"] == "disabled"  # no provider-hosted search past the platform
    assert config["sandbox_mode"] == "danger-full-access"  # a bypass turn: the hooks decide, as for Claude Code
    assert config["mcp_servers"]["octryx_knowledge"]["http_headers_helper"] == f"{wrapper} mcp-headers"
    assert config["mcp_servers"]["octryx_knowledge"]["default_tools_approval_mode"] == "approve"
    pre = config["hooks"]["PreToolUse"][0]["hooks"][0]["command"]
    assert pre.startswith(f"{wrapper} hook pre-tool-use") and pre.endswith("exit 2; }")  # fails closed
    assert {event for event in config["hooks"]} == {"PreToolUse", "PostToolUse", "Stop"}
    text = (home / "config.toml").read_text() + (home / codex_config.ENV_WRAPPER).read_text()
    assert "sk-from-the-shell" not in text
    exported = (home / codex_config.ENV_WRAPPER).read_text()
    assert "OCTRYX_ENGINE=codex" in exported and "OCTRYX_DEFER_STOP=1" in exported
    assert exported.rstrip().endswith('/opt/octryx/bin/octryx-claude "$@"')
    assert "developer_instructions" not in config  # not a story session: the platform's prompt leads
    prepared.extra["plain"] = True
    story = tomllib.loads(codex_driver.prepare_home(prepared, sandboxed=False).joinpath("config.toml").read_text())
    assert "Never commit or push" in story["developer_instructions"]
    prepared.extra.pop("plain")
    terminal = tomllib.loads(codex_driver.prepare_home(prepared, sandboxed=True, interactive=True).joinpath(
        "config.toml").read_text())
    assert "developer_instructions" not in terminal and terminal["approval_policy"] == "on-request"
    env = codex_driver.environment(prepared, home)
    assert "OPENAI_API_KEY" not in env and "ANTHROPIC_BASE_URL" not in env
    assert env["CODEX_HOME"] == str(home) and env["OCTRYX_ENGINE"] == "codex"
    assert tomllib.loads(codex_driver.prepare_home(prepared, sandboxed=True).joinpath("config.toml").read_text())[
        "sandbox_mode"] == "workspace-write"


def test_events_map_to_job_events_and_usage_to_the_platforms_keys():
    assert codex_driver.map_line({"type": "thread.started", "thread_id": "th-1"}) == [
        {"kind": "session", "claude_session_id": "th-1"}]
    started = codex_driver.map_line({"type": "item.started", "item": {
        "id": "i1", "type": "command_execution", "command": "pytest -q", "status": "in_progress"}})
    assert started[0]["kind"] == "tool_use" and started[0]["tool"] == "Bash"
    done = codex_driver.map_line({"type": "item.completed", "item": {
        "id": "i1", "type": "command_execution", "aggregated_output": "1 failed", "exit_code": 1,
        "status": "failed"}})
    assert done == [{"kind": "tool_result", "tool_use_id": "i1", "is_error": True, "output": "1 failed"}]
    assert codex_driver.map_line({"type": "item.completed", "item": {"id": "m", "type": "agent_message",
                                                                     "text": "Done."}}) == [
        {"kind": "text", "text": "Done."}]
    patch = codex_driver.map_line({"type": "item.completed", "item": {
        "id": "p", "type": "file_change", "status": "completed", "changes": [{"path": "a.py", "kind": "update"}]}})
    assert patch[0]["tool"] == "apply_patch" and "update a.py" in patch[0]["input_preview"]
    assert codex_driver.map_line({"type": "turn.failed", "error": {"message": "boom"}})[0]["kind"] == "error"
    assert codex_driver.usage_of({"input_tokens": 1000, "cached_input_tokens": 600, "output_tokens": 50}) == {
        "input_tokens": 400, "cache_read_input_tokens": 600, "cache_creation_input_tokens": 0, "output_tokens": 50}


def test_a_turn_streams_events_reports_the_thread_and_resumes_it(tmp_path, monkeypatch):
    lines = [{"type": "thread.started", "thread_id": "th-42"}, {"type": "turn.started"},
             {"type": "item.completed", "item": {"id": "m1", "type": "agent_message", "text": "Story built."}},
             {"type": "turn.completed", "usage": {"input_tokens": 900, "cached_input_tokens": 100,
                                                  "output_tokens": 30}}]
    codex = _fake_codex(tmp_path / "bin", lines)
    prepared = _prepared(tmp_path, OPENAI_API_KEY="sk-from-the-shell")
    events: list[dict] = []

    async def emit(event):
        events.append(event)

    async def run(resume):
        return await codex_driver.CodexDriver(str(codex)).run_turn(
            prepared, cwd=str(tmp_path), prompt="Build S1", resume=resume, emit=emit)

    result = asyncio.run(run(None))
    assert result["status"] == "success" and result["claude_session_id"] == "th-42"
    assert result["result_text"] == "Story built." and result["usage"]["input_tokens"] == 800
    assert {"kind": "session", "claude_session_id": "th-42"} in events
    called = json.loads((tmp_path / "bin" / "argv.json").read_text())
    assert called["argv"][:3] == ["exec", "--json", "--trust"] and called["argv"][-1] == "Build S1"
    assert called["key"] is None and called["home"].endswith("codex-home")

    events.clear()
    asyncio.run(run("th-42"))
    assert events[0] == {"kind": "session", "claude_session_id": "th-42"}  # named before Codex says anything
    called = json.loads((tmp_path / "bin" / "argv.json").read_text())
    assert called["argv"][-3:] == ["resume", "th-42", "Build S1"]


def test_a_failed_turn_is_an_error_and_an_old_codex_is_refused(tmp_path):
    codex = _fake_codex(tmp_path / "bin", [{"type": "thread.started", "thread_id": "t"},
                                           {"type": "turn.failed", "error": {"message": "upstream"}}])

    async def emit(_event):
        return None

    result = asyncio.run(codex_driver.CodexDriver(str(codex)).run_turn(
        _prepared(tmp_path), cwd=str(tmp_path), prompt="x", resume=None, emit=emit))
    assert result["status"] == "error" and result["error"] == "codex_turn_failed"
    old = _fake_codex(tmp_path / "old", [], version="codex-cli 0.154.0")
    with pytest.raises(codex_driver.CodexUnavailableError) as refused:
        codex_driver.resolve_codex({"OCTRYX_CODEX_PATH": str(old), "PATH": ""})
    assert refused.value.code == "codex_too_old"
    with pytest.raises(codex_driver.CodexUnavailableError) as missing:
        codex_driver.resolve_codex({"PATH": str(tmp_path / "nowhere")})
    assert missing.value.code == "codex_not_installed"


def test_the_terminal_starts_only_an_allowed_engine_and_never_a_bypass():
    from octryx_claude import codex_cli, engine_choice

    only_claude = engine_choice.EngineSetting(engine="claude_code", source="workspace", allowed=("claude_code",),
                                              known=True)
    assert engine_choice.refusal(only_claude, "claude_code") == ""
    assert "engine_not_allowed_in_workspace" in engine_choice.refusal(only_claude, "codex")
    # a platform that does not report engines (older, or unreachable) starts Claude Code, never Codex
    assert engine_choice.refusal(engine_choice.UNKNOWN, "claude_code") == ""
    assert engine_choice.refusal(engine_choice.UNKNOWN, "codex") != ""
    assert "Codex (Workspace default" in engine_choice.EngineSetting(
        engine="codex", source="workspace", allowed=("claude_code", "codex"), known=True).line()
    for bypass in (["--yolo"], ["-c", "model_provider=openai"], ["--config=x"], ["--oss"],
                   ["--dangerously-bypass-approvals-and-sandbox"]):
        assert codex_cli.refused_arg(bypass), bypass
    assert codex_cli.refused_arg(["--search", "explain this repo"]) == ""


def test_the_general_help_names_both_engines():
    from octryx_claude.cli_parsers import launch_parser

    shown = " ".join(launch_parser().format_help().split())
    assert "octryx-claude [claude]" in shown and "octryx-claude codex" in shown and "OpenAI Codex CLI" in shown


def test_every_session_sees_the_devices_codex_threads(tmp_path):
    """The epic's next story runs in a new session and must find the thread of the story before it."""
    first = _prepared(tmp_path, OCTRYX_CLAUDE_HOME=str(tmp_path / "state"))
    home = codex_driver.prepare_home(first, sandboxed=False)
    (home / "sessions" / "2026" ).mkdir(parents=True)
    (home / "sessions" / "2026" / "rollout-x-th-1.jsonl").write_text("{}")
    second = _prepared(tmp_path / "other", OCTRYX_CLAUDE_HOME=str(tmp_path / "state"))
    other = codex_driver.prepare_home(second, sandboxed=False)
    assert (other / "sessions" / "2026" / "rollout-x-th-1.jsonl").read_text() == "{}"
    assert (home / "config.toml").exists() and (other / "config.toml").exists()  # config stays per session


def test_a_stop_that_says_not_done_continues_the_same_thread(tmp_path, monkeypatch):
    """Claude Code goes on in its process when the platform's Stop hook blocks; Codex has ended, so the driver resumes
    the thread with the platform's reason (a spec interview paused after reading the repository)."""
    from octryx_claude import plain_driver

    codex = _fake_codex(tmp_path / "bin", [
        {"type": "thread.started", "thread_id": "th-7"},
        {"type": "item.completed", "item": {"id": "m", "type": "agent_message", "text": "Done."}},
        {"type": "turn.completed", "usage": {"input_tokens": 10, "output_tokens": 1}}])
    answers = [{"decision": "block", "reason": "Phase not finished: record the questions with the tool."}, None]
    monkeypatch.setattr(plain_driver, "replay_stop", lambda _prepared, _cwd: answers.pop(0))
    calls: list[list[str]] = []
    original = codex_driver.command
    monkeypatch.setattr(codex_driver, "command",
                        lambda *a, **k: calls.append(original(*a, **k)) or calls[-1])
    events: list[dict] = []

    async def emit(event):
        events.append(event)

    result = asyncio.run(codex_driver.CodexDriver(str(codex)).run_turn(
        _prepared(tmp_path), cwd=str(tmp_path), prompt="Interview", resume=None, emit=emit))
    assert result["status"] == "success" and len(calls) == 2
    assert calls[1][-3:] == ["resume", "th-7", "Phase not finished: record the questions with the tool."]
    assert result["usage"]["output_tokens"] == 2  # both rounds counted
    assert any(event.get("text", "").startswith("Octryx: Phase not finished") for event in events)


def test_a_too_old_codex_names_the_minimum_the_found_version_and_the_update_command(tmp_path):
    codex = tmp_path / "Cellar" / "codex" / "0.154.0" / "bin" / "codex"
    codex.parent.mkdir(parents=True)
    codex.write_text("#!/bin/sh\necho 'codex-cli 0.1.0'\n")
    codex.chmod(0o755)
    with pytest.raises(codex_driver.CodexUnavailableError) as raised:
        codex_driver.resolve_codex({"OCTRYX_CODEX_PATH": str(codex), "PATH": ""})
    wanted = ".".join(map(str, codex_driver.MIN_VERSION))
    assert raised.value.hint() == (f"needs_configuration: codex_too_old: Codex CLI {wanted} or newer is needed "
                                   "(found 0.1.0); update with: brew upgrade codex")
    assert codex_driver.update_command("/usr/lib/node_modules/@openai/codex/bin/codex.js").startswith("npm install")


def test_codex_stop_hook_has_the_time_to_build_a_large_change(tmp_path):
    """Story path audit: a 40 MB change (hundreds of screenshot baselines) needs up to three git steps of
    CHANGE_GIT_TIMEOUT in the Stop hook; Codex's hook carries the same timeout as Claude Code's."""

    home = codex_driver.prepare_home(_prepared(tmp_path), sandboxed=False)
    stop = tomllib.loads((home / "config.toml").read_text())["hooks"]["Stop"][0]["hooks"][0]
    assert stop["timeout"] == launch_settings.STOP_HOOK_TIMEOUT >= 3 * contract_change.CHANGE_GIT_TIMEOUT + 60
