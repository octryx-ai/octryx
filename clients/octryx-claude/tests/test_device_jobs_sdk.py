"""The SDK driver's options, decisions, messages, sandbox network, change diffs and context fill."""

from __future__ import annotations

from pathlib import Path

import pytest

from octryx_claude.device_sdk import SdkDriver
from octryx_claude.device_sdk_events import map_message
from octryx_claude.device_session import PreparedSession
from tests.device_jobs_support import _fake_sdk


@pytest.mark.asyncio
async def test_sdk_options_pin_the_launcher_session_and_map_decisions():
    sdk = _fake_sdk()
    prepared = PreparedSession(session_key="00000000-0000-4000-8000-000000000001", cli_path="/usr/local/bin/claude",
                               settings_path=Path("/tmp/s.json"), mcp_path=Path("/tmp/m.json"), env={"A": "1"},
                               profile="governed")
    verdicts = iter([("allow", ""), ("allow_job_edits", ""), ("deny", "Denied by the owner in the chat.")])

    async def decide(tool, tool_input):
        return next(verdicts)

    options = SdkDriver(sdk)._options(prepared, cwd="/home/sample/src", resume=None, decide=decide)
    assert options.cli_path == "/usr/local/bin/claude" and options.settings == "/tmp/s.json"
    assert options.permission_mode == "default" and options.setting_sources == ["user", "project", "local"]
    assert options.extra_args == {"strict-mcp-config": None, "session-id": prepared.session_key}
    allow = await options.can_use_tool("Bash", {"command": "ls"}, None)
    assert isinstance(allow, sdk.PermissionResultAllow) and allow.updated_permissions is None
    edits = await options.can_use_tool("Edit", {"file_path": "a"}, None)
    assert edits.updated_permissions[0].mode == "acceptEdits" and edits.updated_permissions[0].destination == "session"
    deny = await options.can_use_tool("Bash", {"command": "rm"}, None)
    assert isinstance(deny, sdk.PermissionResultDeny) and deny.message == "Denied by the owner in the chat."
    resumed = SdkDriver(sdk)._options(prepared, cwd="/x", resume="cs-1", decide=decide)
    assert resumed.resume == "cs-1" and "session-id" not in resumed.extra_args
    assert options.model is None  # the launcher's main alias
    prepared.model = "company/co-sonnet"
    chosen = SdkDriver(sdk)._options(prepared, cwd="/x", resume="cs-1", decide=decide)
    assert chosen.model == "company/co-sonnet" and chosen.resume == "cs-1"


@pytest.mark.asyncio
async def test_an_open_sandbox_network_reaches_other_hosts_without_asking_but_never_the_platform():
    sdk = _fake_sdk()
    asked = []

    async def decide(tool, tool_input):
        asked.append(tool_input["host"])
        return "deny", "no"

    def options(**extra):
        prepared = PreparedSession(session_key="k", cli_path="claude", settings_path=Path("s.json"),
                                   mcp_path=Path("m.json"), env={}, profile="governed", extra=extra)
        return SdkDriver(sdk)._options(prepared, cwd="/x", resume=None, decide=decide)

    opened = options(sandbox_network="open", denied_hosts=["octryx.example.test"])
    allowed = await opened.can_use_tool("SandboxNetworkAccess", {"host": "pypi.org", "port": 443}, None)
    assert isinstance(allowed, sdk.PermissionResultAllow) and asked == []
    await opened.can_use_tool("SandboxNetworkAccess", {"host": "OCTRYX.example.test", "port": 443}, None)
    await options().can_use_tool("SandboxNetworkAccess", {"host": "pypi.org", "port": 443}, None)
    assert asked == ["OCTRYX.example.test", "pypi.org"]


def test_sdk_messages_map_to_chat_events():
    def message(class_name, **fields):
        return type(class_name, (), fields)()

    tool_use = message("ToolUseBlock", name="Bash", id="tu1", input={"command": "pytest -q"})
    result = message("ToolResultBlock", tool_use_id="tu1", is_error=True, content="x" * 5000)
    assert map_message(message("SystemMessage", subtype="init", data={"session_id": "cs-9"})) == [
        {"kind": "session", "claude_session_id": "cs-9"}]
    assert map_message(message("SystemMessage", subtype="init", data={"session_id": "cs-9", "model": "co-x"})) == [
        {"kind": "session", "claude_session_id": "cs-9", "model": "co-x"}]
    assert map_message(message("StreamEvent", event={"delta": {"type": "text_delta", "text": "Hi"}})) == [
        {"kind": "text_delta", "text": "Hi"}]
    assert map_message(message("AssistantMessage", content=[tool_use])) == [
        {"kind": "tool_use", "tool": "Bash", "tool_use_id": "tu1", "input_preview": "pytest -q"}]
    mapped = map_message(message("UserMessage", content=[result]))[0]
    assert mapped["is_error"] is True and len(mapped["output"]) == 4001


def test_a_code_change_carries_its_diff_for_the_app():
    from octryx_claude.device_sdk_events import change_diff

    diff = change_diff("Edit", {"file_path": "/repo/a.py", "old_string": "x = 1\ny = 2", "new_string": "x = 1\ny = 3"})
    assert diff.startswith("--- /repo/a.py") and "-y = 2" in diff and "+y = 3" in diff
    multi = change_diff("MultiEdit", {"file_path": "/repo/b.py", "edits": [{"old_string": "a", "new_string": "b"}]})
    assert "-a" in multi and "+b" in multi
    assert change_diff("Write", {"file_path": "/repo/n.md", "content": "hello\nworld"}).endswith("+hello\n+world")
    assert change_diff("Bash", {"command": "ls"}) == ""
    assert len(change_diff("Write", {"file_path": "/r", "content": "x\n" * 20000})) == 8000


def test_no_diff_of_a_secret_file_leaves_the_mac():
    from octryx_claude.device_sdk_events import change_diff

    for path in ("/repo/.env", "/repo/.env.local", "/repo/certs/server.pem", "/home/u/.ssh/id_ed25519",
                 "/repo/config/credentials.json", "/repo/db.key", "/home/u/.aws/config"):
        assert change_diff("Write", {"file_path": path, "content": "API_KEY=abc"}) == "", path
        assert change_diff("Edit", {"file_path": path, "old_string": "a", "new_string": "b"}) == "", path
    assert change_diff("Write", {"file_path": "/repo/README.md", "content": "hello"}) != ""


def test_context_fill_comes_from_the_main_threads_last_call():
    from octryx_claude.device_sdk_events import context_tokens, context_window

    class AssistantMessage:
        def __init__(self, usage, parent=None):
            self.usage, self.parent_tool_use_id = usage, parent

    usage = {"input_tokens": 2, "cache_read_input_tokens": 40000, "cache_creation_input_tokens": 3000,
             "output_tokens": 500}
    assert context_tokens(AssistantMessage(usage)) == 43502
    assert context_tokens(AssistantMessage(usage, parent="toolu_1")) is None
    assert context_tokens(AssistantMessage(None)) is None
    windows = {"claude-opus-5-5": {"contextWindow": 1000000}, "claude-haiku-5-5": {"contextWindow": 200000}}
    assert context_window(windows) == 1000000
    assert context_window(None) == 0
