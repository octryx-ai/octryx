from __future__ import annotations

import sys
import tomllib

import pytest

from octryx_claude import codex_config, codex_driver, codex_events, codex_trust, contract_change, launch_settings
from tests.codex_appserver_fake import fake_appserver
from tests.codex_driver_support import _prepared


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
    assert pre.startswith(f"{wrapper} hook pre-tool-use ||") and pre.endswith("exit 2; }")  # fails closed
    assert {event for event in config["hooks"] if event != "state"} == {"PreToolUse", "PostToolUse", "Stop"}
    text = (home / "config.toml").read_text() + (home / codex_config.ENV_WRAPPER).read_text()
    assert "sk-from-the-shell" not in text
    exported = (home / codex_config.ENV_WRAPPER).read_text()
    assert "OCTRYX_ENGINE=codex" in exported and "OCTRYX_DEFER_STOP:=1" in exported
    assert exported.rstrip().endswith('"$@"') and "from octryx_claude.entry import main" in exported
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
    review = tomllib.loads(codex_driver.prepare_home(prepared, sandboxed=True).joinpath("config.toml").read_text())
    assert (review["sandbox_mode"], review["approval_policy"]) == ("workspace-write", "never")
    turn = tomllib.loads(codex_driver.prepare_home(prepared, sandboxed=True, device_turn=True).joinpath(
        "config.toml").read_text())
    assert turn["approval_policy"] == "on-request"


def test_in_a_container_the_container_is_the_sandbox(tmp_path):
    prepared = _prepared(tmp_path, OCTRYX_CODEX_CONTAINER_BOUNDARY="1")
    config = tomllib.loads(codex_driver.prepare_home(prepared, sandboxed=True).joinpath("config.toml").read_text())
    assert config["sandbox_mode"] == "danger-full-access"


def test_the_launchers_hook_hash_is_the_one_codex_computes():
    hook = codex_trust.HookDeclaration("PreToolUse", "octryx-env.sh hook pre-tool-use || { exit 2; }", 20)
    # Reported by codex-cli 0.169.0 hooks/list for this declaration.
    assert codex_trust.declaration_hash(hook) == (
        "sha256:a71b9509224b4df7d3096de79fd5ced3f8d2446b7e5b202853a39c81e82efd5c")


def test_tool_shells_get_no_platform_credentials(tmp_path):
    review = tomllib.loads(codex_driver.prepare_home(_prepared(tmp_path / "a"), sandboxed=True).joinpath(
        "config.toml").read_text())
    assert "shell_environment_policy" not in review
    home = codex_driver.prepare_home(_prepared(tmp_path / "b"), sandboxed=True, device_turn=True)
    config = tomllib.loads((home / "config.toml").read_text())
    policy = config["shell_environment_policy"]
    assert policy == {"inherit": "all", "ignore_default_excludes": False,
                      "exclude": ["OCTRYX_*", "ANTHROPIC_*", "CLAUDE_CODE_*"]}
    pre = config["hooks"]["PreToolUse"][0]["hooks"][0]["command"]
    assert pre.startswith("exec ") and "codex_hook_guard.py" in pre and "||" not in pre
    prepared = _prepared(tmp_path / "c", OCTRYX_TURN_MARK="mark-1", OCTRYX_PASSWORD="dev-secret",
                         OCTRYX_CODEX_SEAT_CREDENTIAL="seat-secret")
    assert codex_config.shell_environment(prepared)["set"] == {"OCTRYX_TURN_MARK": "mark-1"}
    home = codex_driver.prepare_home(prepared, sandboxed=True, device_turn=True)
    wrapper = (home / codex_config.ENV_WRAPPER).read_text()
    assert "OCTRYX_TURN_MARK" in wrapper and "dev-secret" not in wrapper and "seat-secret" not in wrapper
    assert "OCTRYX_PASSWORD" not in codex_driver.environment(prepared, home)


def test_items_map_to_job_events_and_usage_to_the_platforms_keys():
    started = codex_events.map_item("item/started", {"id": "i1", "type": "commandExecution", "command": "pytest -q"})
    assert started[0]["kind"] == "tool_use" and started[0]["tool"] == "Bash"
    done = codex_events.map_item("item/completed", {"id": "i1", "type": "commandExecution", "status": "completed",
                                                    "aggregatedOutput": "1 failed", "exitCode": 1})
    assert done == [{"kind": "tool_result", "tool_use_id": "i1", "is_error": True, "output": "1 failed"}]
    assert codex_events.map_item("item/completed", {"id": "m", "type": "agentMessage", "text": "Done."}) == [
        {"kind": "text", "text": "Done."}]
    patch = codex_events.map_item("item/completed", {"id": "p", "type": "fileChange", "status": "completed",
                                                     "changes": [{"path": "a.py", "kind": {"type": "update"}}]})
    assert patch[0]["tool"] == "apply_patch" and "update a.py" in patch[0]["input_preview"]
    mcp = codex_events.map_item("item/completed", {"id": "c", "type": "mcpToolCall", "server": "octryx_knowledge",
                                                   "tool": "search", "status": "failed", "error": {"message": "x"}})
    assert mcp[0]["is_error"] is True
    assert codex_events.usage_of({"inputTokens": 1000, "cachedInputTokens": 600, "outputTokens": 50}) == {
        "input_tokens": 400, "cache_read_input_tokens": 600, "cache_creation_input_tokens": 0, "output_tokens": 50}


def test_a_blocked_pre_tool_use_hook_shows_as_a_denied_tool_call():
    run = {"id": "r1", "eventName": "preToolUse", "status": "blocked",
           "entries": [{"kind": "feedback", "text": "Octryx policy denied this tool call"}]}
    use, result = codex_events.map_hook(run)
    assert use["kind"] == "tool_use" and use["tool_use_id"] == result["tool_use_id"]
    assert result["is_error"] is True and "denied" in result["output"]
    assert codex_events.map_hook({**run, "status": "completed"}) == []
    assert codex_events.map_hook({**run, "eventName": "stop"}) == []


def test_seat_limits_come_from_codexs_error_kind_or_account_message():
    assert codex_events.limit_code({"codexErrorInfo": "usageLimitExceeded", "message": ""}) == "usage_limit"
    assert codex_events.limit_code({"codexErrorInfo": "rateLimitExceeded", "message": ""}) == "rate_limit"
    assert codex_events.limit_code({"codexErrorInfo": {"httpConnectionFailed": {"httpStatusCode": 429}},
                                    "message": ""}) == "rate_limit"
    assert codex_events.limit_code({"message": "You've hit your usage limit. Try again later."}) == "usage_limit"
    assert codex_events.limit_code({"codexErrorInfo": "serverOverloaded", "message": "rate limit words"}) == ""


def test_an_old_or_missing_codex_is_refused(tmp_path):
    old = fake_appserver(tmp_path / "old", version="codex-cli 0.154.0")
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
    first = _prepared(tmp_path, OCTRYX_CLAUDE_HOME=str(tmp_path / "state"))
    home = codex_driver.prepare_home(first, sandboxed=False)
    (home / "sessions" / "2026" ).mkdir(parents=True)
    (home / "sessions" / "2026" / "rollout-x-th-1.jsonl").write_text("{}")
    second = _prepared(tmp_path / "other", OCTRYX_CLAUDE_HOME=str(tmp_path / "state"))
    other = codex_driver.prepare_home(second, sandboxed=False)
    assert (other / "sessions" / "2026" / "rollout-x-th-1.jsonl").read_text() == "{}"
    assert (home / "config.toml").exists() and (other / "config.toml").exists()  # config stays per session


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

    home = codex_driver.prepare_home(_prepared(tmp_path), sandboxed=False)
    stop = tomllib.loads((home / "config.toml").read_text())["hooks"]["Stop"][0]["hooks"][0]
    assert stop["timeout"] == launch_settings.STOP_HOOK_TIMEOUT >= 3 * contract_change.CHANGE_GIT_TIMEOUT + 60


def test_the_wrapper_starts_the_launcher_by_absolute_path_isolated_from_the_work_folder(tmp_path):
    prepared = _prepared(tmp_path, PATH=f"{tmp_path}/repo/.venv/bin:/usr/bin:/bin", PYTHONPATH=f"{tmp_path}/repo/src")
    home = codex_driver.prepare_home(prepared, sandboxed=True, device_turn=True)
    wrapper = (home / codex_config.ENV_WRAPPER).read_text()
    assert wrapper.startswith("#!/bin/sh\n")
    assert f"OCTRYX_TEST_RUN_SHIM={home / codex_config.ENV_WRAPPER}" in wrapper  # wrapped test runs keep the session
    assert "unset PYTHONPATH PYTHONHOME" in wrapper and str(tmp_path / "repo") not in wrapper
    assert f"exec {sys.executable} -I -c" in wrapper and "/usr/bin/env" not in wrapper


def test_the_hook_chain_counts_as_writable_by_path_or_by_link(tmp_path):
    work = tmp_path / "work"
    (work / ".venv" / "bin").mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    (work / "link").symlink_to(outside)
    roots = codex_trust.sandbox_roots({"excludeTmpdirEnvVar": True, "excludeSlashTmp": True}, str(work))
    assert codex_trust.writable_in_sandbox([work / ".venv" / "bin" / "python"], roots)
    assert codex_trust.writable_in_sandbox([work / "link" / "guard.py"], roots)  # the path lies in the work folder
    assert not codex_trust.writable_in_sandbox([outside / "guard.py"], roots)
    assert codex_trust.writable_in_sandbox([outside / "guard.py"], codex_trust.sandbox_roots(
        {"writableRoots": [str(outside)], "excludeTmpdirEnvVar": True, "excludeSlashTmp": True}, str(work)))


def test_the_real_stop_replay_through_the_wrapper_reaches_the_verification(tmp_path, monkeypatch):
    import json

    from octryx_claude import hooks, plain_driver

    monkeypatch.setattr(plain_driver, "REPLAY_RETRY_SECONDS", 0)
    key = "00000000-0000-4000-8000-0000000000ee"
    prepared = _prepared(tmp_path, OCTRYX_BASE_URL="http://127.0.0.1:9", OCTRYX_SESSION_KEY=key)
    prepared.session_key = key
    prepared.extra["gateway"]["base_url"] = "http://127.0.0.1:9"
    home = codex_driver.prepare_home(prepared, sandboxed=True, device_turn=True)
    stop = tmp_path / "sessions" / key / hooks.DEFERRED_STOP_FILE
    stop.parent.mkdir(parents=True, exist_ok=True)
    stop.write_text(json.dumps({"hook_event_name": "Stop", "session_id": "th-1", "turn_id": "turn-1",
                                "cwd": str(tmp_path), "stop_hook_active": False}))
    answer, judged = plain_driver.judged_stop(prepared, str(tmp_path), str(home / codex_config.ENV_WRAPPER))
    verdict = plain_driver.stop_verdict(prepared)
    # The hook ran the verification (it did not defer the Stop again) and recorded the platform's verdict.
    assert (verdict["session_id"], verdict["turn_id"]) == ("th-1", "turn-1")
    assert verdict["outcome"] != "ok" and judged is False  # nobody answers on 127.0.0.1:9
    assert not stop.exists()


def test_a_wrapped_test_run_keeps_the_shells_pythonpath_and_hooks_do_not(tmp_path):
    import subprocess

    prepared = _prepared(tmp_path)
    home = codex_driver.prepare_home(prepared, sandboxed=True, device_turn=True)
    wrapper = (home / codex_config.ENV_WRAPPER).read_text()
    probe = home / "probe.sh"  # the wrapper with its launcher replaced by a print of what it would get
    probe.write_text(wrapper.rsplit("exec ", 1)[0] + 'echo "$1|$PYTHONPATH|$OCTRYX_DEFER_STOP"\n')
    probe.chmod(0o700)

    def run(*args, **env):
        return subprocess.run(["/bin/sh", str(probe), *args], capture_output=True, text=True, check=True,
                              env={"PATH": "/usr/bin:/bin", "PYTHONPATH": "/work/src", **env}).stdout.strip()

    assert run("test-run", "x") == "test-run|/work/src|1"
    assert run("hook", "pre-tool-use") == "hook||1"
    assert run("hook", "stop", OCTRYX_DEFER_STOP="0") == "hook||0"


def test_codex_streams_its_answer_as_text_deltas_before_the_whole_message(tmp_path, monkeypatch):
    import asyncio

    from octryx_claude import codex_driver, plain_driver
    from tests.codex_appserver_fake import fake_appserver
    from tests.codex_driver_support import _prepared, _stop_replay

    monkeypatch.setattr(plain_driver, "judged_stop", _stop_replay((None, True)))
    codex = fake_appserver(tmp_path / "bin", turns=[[
        {"notify": "item/agentMessage/delta", "params": {"itemId": "a", "delta": "Hel"}},
        {"notify": "item/agentMessage/delta", "params": {"itemId": "a", "delta": "lo."}},
        {"notify": "item/completed", "params": {"item": {"id": "a", "type": "agentMessage", "text": "Hello."}}},
        {"status": "completed"}]])
    events: list[dict] = []

    async def emit(event):
        events.append(event)

    asyncio.run(codex_driver.CodexDriver(str(codex)).run_turn(_prepared(tmp_path), cwd=str(tmp_path), prompt="x",
                                                              resume=None, emit=emit))
    texts = [(event["kind"], event["text"]) for event in events if event["kind"] in ("text_delta", "text")]
    assert texts == [("text_delta", "Hel"), ("text_delta", "lo."), ("text", "Hello.")]


def test_a_compact_turn_compacts_the_thread_and_reports_how_full_its_context_is(tmp_path, monkeypatch):
    import asyncio
    import json

    from octryx_claude import codex_driver, plain_driver
    from tests.codex_appserver_fake import fake_appserver
    from tests.codex_driver_support import _prepared, _stop_replay

    monkeypatch.setattr(plain_driver, "judged_stop", _stop_replay((None, True)))
    usage = {"last": {"totalTokens": 12000, "inputTokens": 11000, "cachedInputTokens": 0, "outputTokens": 1000,
                      "reasoningOutputTokens": 0},
             "total": {"totalTokens": 90000, "inputTokens": 80000, "cachedInputTokens": 0, "outputTokens": 10000,
                       "reasoningOutputTokens": 0},
             "modelContextWindow": 200000}
    codex = fake_appserver(tmp_path / "bin", turns=[[
        {"notify": "thread/tokenUsage/updated", "params": {"tokenUsage": usage}}, {"status": "completed"}]])
    prepared = _prepared(tmp_path)
    events: list[dict] = []

    async def emit(event):
        events.append(event)

    result = asyncio.run(codex_driver.CodexDriver(str(codex)).run_turn(prepared, cwd=str(tmp_path), prompt="/compact",
                                                                       resume="th-1", emit=emit))
    assert result["status"] == "success"
    assert {"kind": "context", "used": 12000, "window": 200000} in events
    methods = [json.loads(line).get("method") for line in (tmp_path / "bin" / "calls.jsonl").read_text().splitlines()]
    assert "thread/compact/start" in methods and "turn/start" not in methods


def test_a_gateway_alias_gets_its_context_window_from_the_platform(tmp_path):
    import tomllib

    from octryx_claude import codex_driver
    from tests.codex_driver_support import _prepared

    prepared = _prepared(tmp_path)
    prepared.extra["model_context_window"] = 200000
    home = codex_driver.prepare_home(prepared, sandboxed=False)
    assert tomllib.loads((home / "config.toml").read_text())["model_context_window"] == 200000
    bare = _prepared(tmp_path / "bare")
    assert "model_context_window" not in tomllib.loads(
        (codex_driver.prepare_home(bare, sandboxed=False) / "config.toml").read_text())
