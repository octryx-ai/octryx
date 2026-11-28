from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from octryx_claude import launch, launch_process, launch_sandbox, launch_settings

SHIM = Path("/opt/octryx kit/bin/octryx-claude")
KEY = ("0b6c" + "4a52-3b1e-4c1b-9f55-1d1c1b1a1f10")


def _model_env(work_item: str = "OCX-615") -> dict[str, str]:
    return launch.model_env(
        base_url="https://octryx.example.test",
        session_key=KEY,
        workspace_id="ws-1",
        work_item=work_item,
        aliases={"main": "claude-sonnet-5", "opus": "claude-opus-5-5", "small_fast": "claude-sonnet-5"},
    )


def test_model_env_routes_every_model_through_the_gateway_with_session_headers():
    env = _model_env()
    assert env["ANTHROPIC_BASE_URL"] == "https://octryx.example.test/api/v1/model-gateway/anthropic"
    assert env["ANTHROPIC_CUSTOM_HEADERS"] == (
        f"X-Octryx-Session: {KEY}\n"
        "X-Octryx-Workspace: ws-1\n"
        "X-Octryx-Work-Item: OCX-615"
    )
    assert env["ANTHROPIC_MODEL"] == env["CLAUDE_CODE_SUBAGENT_MODEL"] == "claude-sonnet-5"
    assert env["ANTHROPIC_DEFAULT_HAIKU_MODEL"] == env["ANTHROPIC_SMALL_FAST_MODEL"] == "claude-sonnet-5"
    assert env["ANTHROPIC_DEFAULT_OPUS_MODEL"] == "claude-opus-5-5"
    assert env["CLAUDE_CODE_API_KEY_HELPER_TTL_MS"] == "600000"
    assert env["CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS"] == "1"
    assert env["CLAUDE_CODE_USE_BEDROCK"] == "" and env["CLAUDE_CODE_USE_VERTEX"] == ""
    assert "X-Octryx-Work-Item" not in _model_env(work_item="")["ANTHROPIC_CUSTOM_HEADERS"]


def test_settings_pin_helper_policy_rules_and_fail_closed_hooks():
    policy = {
        "state": "allowed",
        "permissions": {"deny": ["Bash(git push origin main:*)", 42, "x" * 400], "ask": ["Bash(kubectl:*)"]},
    }
    settings = launch_settings.build_settings(
        shim=SHIM, state_root=Path("/Users/u/.octryx/claude"), env=_model_env(), policy=policy,
        base_url="https://octryx.example.test",
    )
    assert settings["sandbox"] == {
        "enabled": True,
        "failIfUnavailable": True,
        "allowUnsandboxedCommands": False,
        "filesystem": {"denyRead": ["/Users/u/.octryx/claude"]},
        "network": {"deniedDomains": ["octryx.example.test"], "allowLocalBinding": True},
        # The launcher's test-run wrapper is the one form that leaves the sandbox (``local_tests``).
        "excludedCommands": [f"'{SHIM}' test-run *"],
    }
    for base_url, denied in (("http://localhost:8090", ["localhost", "127.0.0.1"]),
                             ("http://127.0.0.1:8000", ["127.0.0.1", "localhost"])):
        loopback = launch_sandbox.sandbox_settings(state_root=Path("/s"), base_url=base_url)
        assert loopback["network"]["deniedDomains"] == denied
    # The Workspace's admin-edited sandbox domains reach Claude Code; malformed or platform entries never do.
    workspace = {"sandbox": {"allowed_domains": [
        "pypi.org", "*.npmjs.org", "https://x.example", "*.octryx.example.test", 7,
        "pypi.org",
    ]}}
    configured = launch_sandbox.sandbox_settings(
        state_root=Path("/s"), base_url="https://octryx.example.test", policy=workspace
    )
    assert configured["network"] == {
        "deniedDomains": ["octryx.example.test"], "allowLocalBinding": True,
        "allowedDomains": ["pypi.org", "*.npmjs.org"],
    }
    # The Workspace's declared system test commands run outside the sandbox (server port, browser).
    system = {"sandbox": {"unsandboxed_commands": [".venv/bin/python -m pytest -v tests/system", "", 5,
                                                   ".venv/bin/python -m pytest -v tests/system"]}}
    unsandboxed = launch_sandbox.sandbox_settings(
        state_root=Path("/s"), base_url="https://octryx.example.test", policy=system)
    assert unsandboxed["excludedCommands"] == [".venv/bin/python -m pytest -v tests/system"]
    assert "excludedCommands" not in configured
    # ``sandbox.network: open`` keeps the same lists (Claude Code refuses "*" in
    # allowedDomains); the device turn answers the sandbox's question for another host (``device_sdk``).
    opened = {"sandbox": {"network": "open", "allowed_domains": ["*.npmjs.org"]}}
    assert launch_sandbox.sandbox_network(opened) == "open" and launch_sandbox.sandbox_network(workspace) == "allowlist"
    assert launch_sandbox.sandbox_settings(state_root=Path("/s"), base_url="https://octryx.example.test",
                                   policy=opened)["network"]["deniedDomains"] == ["octryx.example.test"]

    assert settings["apiKeyHelper"] == "'/opt/octryx kit/bin/octryx-claude' api-key-helper"
    assert settings["permissions"]["deny"] == [
        "Read(//Users/u/.octryx/claude/**)",
        "Edit(//Users/u/.octryx/claude/**)",
        "Bash(git push origin main:*)",
    ]
    assert settings["permissions"]["ask"] == ["Bash(kubectl:*)"]
    # bypass mode as in plain Claude Code (the hook and the deny rules above still run) ...
    assert "disableBypassPermissionsMode" not in settings["permissions"]
    assert settings["disableAllHooks"] is False
    hooks = settings["hooks"]
    assert set(hooks) == {"PreToolUse", "PostToolUse", "PostToolUseFailure", "Stop", "SubagentStop", "SessionEnd",
                          "UserPromptSubmit", "UserPromptExpansion", "PreCompact", "SessionStart",
                          "PostCompact"}
    prompt_hook = hooks["UserPromptSubmit"][0]["hooks"][0]  # freeze 3c: /handoff runs before any model call
    assert prompt_hook["command"].endswith("hook user-prompt-submit")
    assert prompt_hook["timeout"] == launch_settings.USER_PROMPT_SUBMIT_HOOK_TIMEOUT
    for event in ("PostToolUse", "PostToolUseFailure"):
        [entry] = hooks[event]
        assert entry["matcher"] == "*"  # Every tool result passes the content check
        assert entry["hooks"] == [{
            "type": "command", "command": "'/opt/octryx kit/bin/octryx-claude' hook post-tool-use",
            "timeout": launch_settings.POST_TOOL_USE_HOOK_TIMEOUT,
        }]
    pre = hooks["PreToolUse"][0]
    assert pre["matcher"] == "*"
    assert pre["hooks"][0]["command"].startswith("'/opt/octryx kit/bin/octryx-claude' hook pre-tool-use || ")
    assert pre["hooks"][0]["command"].endswith("exit 2; }")
    assert hooks["SessionEnd"][0]["hooks"][0]["timeout"] == launch_settings.SESSION_END_HOOK_TIMEOUT

    mcp = launch_settings.build_mcp_config(shim=SHIM, base_url="https://octryx.example.test")
    server = mcp["mcpServers"][launch_settings.MCP_SERVER_NAME]
    assert server == {
        "type": "http",
        "url": "https://octryx.example.test/api/v1/mcp/knowledge-protocol/mcp",
        "headersHelper": "'/opt/octryx kit/bin/octryx-claude' mcp-headers",
    }


def test_child_env_scrubs_rerouting_credentials_and_sets_the_session():
    parent = {
        "PATH": "/usr/bin",
        "AWS_PROFILE": "dev",
        "ANTHROPIC_API_KEY": "sk-ant-x",
        "ANTHROPIC_AUTH_TOKEN": "t",
        "CLAUDE_CODE_USE_BEDROCK": "1",
        "AWS_BEARER_TOKEN_BEDROCK": "b",
        "CLAUDE_CODE_OAUTH_TOKEN": "o",
        "OCTRYX_WORK_ITEM": "stale",
    }
    env = launch.build_child_env(
        parent,
        model=_model_env(),
        state_root=Path("/s"),
        claude_config_dir=Path("/s/claude-config"),
        base_url="https://octryx.example.test",
        session_key=KEY,
        workspace_id="ws-1",
        work_item="",
    )
    for name in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "CLAUDE_CODE_USE_BEDROCK",
                 "AWS_BEARER_TOKEN_BEDROCK", "CLAUDE_CODE_OAUTH_TOKEN", "OCTRYX_WORK_ITEM"):
        assert name not in env
    from octryx_claude import tools

    # The parent's PATH first; the launcher's tools (the style gate's ruff, ast-grep …) after it (attempt 4).
    assert env["PATH"].split(os.pathsep) == ["/usr/bin", *tools.bin_dirs(Path("/s"))] and env["AWS_PROFILE"] == "dev"
    assert env["CLAUDE_CONFIG_DIR"] == "/s/claude-config"
    assert env["OCTRYX_SESSION_KEY"] == KEY and env["OCTRYX_WORKSPACE_ID"] == "ws-1"
    assert env["ANTHROPIC_BASE_URL"].endswith("/api/v1/model-gateway/anthropic")


def test_argv_carries_generated_config_and_refuses_overriding_flags():
    argv = launch_process.build_claude_argv(
        "/bin/claude", settings_path=Path("/s/settings.json"), mcp_path=Path("/s/mcp.json"),
        session_key=KEY, user_args=["-p", "hi"],
    )
    assert argv == ["/bin/claude", "--settings", "/s/settings.json", "--strict-mcp-config",
                    "--mcp-config", "/s/mcp.json", "--session-id", KEY, "-p", "hi"]
    resumed = launch_process.build_claude_argv(
        "/bin/claude", settings_path=Path("/s/a"), mcp_path=Path("/s/b"), session_key=KEY, user_args=["--resume"],
    )
    assert "--session-id" not in resumed
    for flag in ("--settings=/tmp/x.json", "--bare", "--dangerously-skip-permissions", "--mcp-config"):
        with pytest.raises(launch.LaunchRefusedError) as caught:
            launch_process.build_claude_argv("/bin/claude", settings_path=Path("/a"), mcp_path=Path("/b"),
                                     session_key=KEY, user_args=[flag])
        assert caught.value.code == "flag_not_allowed"


def test_mcp_headers_carry_the_session_so_board_posts_are_the_session_agent(state, monkeypatch, capsys):
    from octryx_claude import cli_account

    monkeypatch.setattr(cli_account, "get_access_token", lambda state, audience, http: "mcp-token")
    monkeypatch.setenv("OCTRYX_BASE_URL", "https://octryx.example.test")
    monkeypatch.setenv("OCTRYX_SESSION_KEY", KEY)
    monkeypatch.setenv("OCTRYX_WORKSPACE_ID", "ws-1")
    monkeypatch.setenv("OCTRYX_WORK_ITEM", "BRD-6")
    assert cli_account.mcp_headers(state) == 0
    headers = {name.lower(): value for name, value in json.loads(capsys.readouterr().out).items()}
    assert headers == {"authorization": "Bearer mcp-token", "x-octryx-session": KEY,
                       "x-octryx-workspace": "ws-1", "x-octryx-work-item": "BRD-6"}


def test_a_workspace_can_switch_bypass_mode_off(tmp_path):
    from octryx_claude.launch_settings import build_settings

    policy = {"permissions": {"deny": [], "ask": [], "bypass_permissions": "disabled"}}
    settings = build_settings(shim=Path("/bin/octryx-claude"), state_root=tmp_path, env={}, policy=policy,
                              base_url="https://octryx.example.test")
    assert settings["permissions"]["disableBypassPermissionsMode"] == "disable"
    assert "pre-tool-use" in settings["hooks"]["PreToolUse"][0]["hooks"][0]["command"]


def test_a_workflow_runs_turns_keep_claude_codes_own_compaction():
    from octryx_claude import launch

    run = launch.model_env(base_url="https://octryx.example", session_key="00000000-0000-0000-0000-000000000001",
                           workspace_id="w", work_item="", aliases={}, workflow_run="run-1")
    chat = launch.model_env(base_url="https://octryx.example", session_key="00000000-0000-0000-0000-000000000001",
                            workspace_id="w", work_item="", aliases={})
    for env in (run, chat):
        assert "CLAUDE_CODE_AUTO_COMPACT_WINDOW" not in env and "CLAUDE_AUTOCOMPACT_PCT_OVERRIDE" not in env


def test_a_run_sessions_commits_carry_the_ai_output_trailers():
    from octryx_claude import launch

    got = launch.run_attribution("claude-haiku-5-5", {"run": {"ticket_key": "OCX-14", "id": "r1"}})
    assert got == {"commit": "AI-Generated-By-octryx: claude-haiku-5-5\nOctryx-Run: OCX-14", "pr": ""}
    assert launch.run_attribution("", None)["commit"] == "AI-Generated-By-octryx: unknown"
    assert "\n" not in launch.run_attribution("x\nInjected: y", {"run": {"ticket_key": "OCX-1\nX"}})["commit"].split(
        "\n")[0][len("AI-Generated-By-octryx: "):]


def test_node_goes_through_the_sandboxs_proxy():
    settings = launch_settings.build_settings(shim=SHIM, state_root=Path("/Users/u/.octryx/claude"),
                                     env=_model_env(), policy={}, base_url="https://octryx.example.test")
    assert settings["env"]["NODE_USE_ENV_PROXY"] == "1"


def test_a_turn_gets_its_profiles_config_dir_whatever_the_launcher_inherited(tmp_path, monkeypatch):
    from octryx_claude.state import seat_config_dir

    monkeypatch.setenv("OCTRYX_CLAUDE_SEAT_CONFIG_DIR", str(tmp_path / "seat"))
    inherited = {"PATH": "/usr/bin", "CLAUDE_CONFIG_DIR": "/Users/someone/.claude-private"}
    for profile, folder in (("governed", Path("/s/claude-config")), ("seat", seat_config_dir(Path("/s")))):
        env = launch.build_child_env(inherited, model=_model_env(), state_root=Path("/s"), claude_config_dir=folder,
                                     base_url="https://octryx.example.test", session_key=KEY, workspace_id="ws-1",
                                     work_item="", profile=profile)
        assert env["CLAUDE_CONFIG_DIR"] == str(folder) != inherited["CLAUDE_CONFIG_DIR"], profile
    assert str(seat_config_dir(Path("/s"))) == str(tmp_path / "seat")
