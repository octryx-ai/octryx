"""Codex hook decisions: patches per file, ask as deny, platform tool names, view_image and browser calls."""

from __future__ import annotations

import tomllib

import pytest

from octryx_claude import (
    browser_rules,
    codex_config,
    codex_driver,
    codex_hook_input,
    local_decisions,
    pre_tool_use_hook,
)
from tests.codex_driver_support import _prepared

PATCH = ("*** Begin Patch\n*** Add File: src/new.py\n+print(1)\n*** Update File: src/app.py\n@@\n-a\n+b\n"
         "*** End Patch\n")


BROWSER_SPEC = {"type": "stdio", "command": "/opt/homebrew/bin/node",
                "args": ["/state/browser-mcp/0.0.84/node_modules/@playwright/mcp/cli.js", "--headless",
                         "--user-data-dir", "/state/sessions/k1/browser-profile", "--config",
                         "/state/sessions/k1/browser-mcp-config.json", "--browser", "chromium", "--allowed-origins",
                         "http://127.0.0.1:*;http://localhost:*", "--blocked-origins", "http://127.0.0.1:24600"],
                "env": {"PLAYWRIGHT_BROWSERS_PATH": "/state/browser-mcp/0.0.84/browsers"}}


def test_a_patch_is_decided_per_file_and_one_denied_file_denies_it(tmp_path):
    root = tmp_path / "repo"
    (root / "src").mkdir(parents=True)
    assert codex_hook_input.patch_paths(PATCH) == [("Write", "src/new.py"), ("Edit", "src/app.py")]
    policy = {"root": str(root), "state_root": str(tmp_path / "state")}
    contract = {"run": {"status": "running"}, "phase": {"shell": "free"}}
    inside = {"tool_name": "apply_patch", "cwd": str(root), "tool_input": {"command": PATCH}}
    verdicts = [local_decisions.decide(part, policy, contract) for part in codex_hook_input.split_apply_patch(inside)]
    assert [part["tool_input"]["file_path"] for part in codex_hook_input.split_apply_patch(inside)] == [
        str(root / "src/new.py"), str(root / "src/app.py")]
    outside = {**inside, "tool_input": {"command": PATCH.replace("src/app.py", "../../etc/hosts")}}
    assert all(verdict[0] == local_decisions.ALLOW for verdict in verdicts)
    assert local_decisions.decide(inside, policy, contract)[0] == local_decisions.ALLOW
    # one file outside the repository: the platform decides the whole patch
    assert local_decisions.decide(outside, policy, contract)[0] == local_decisions.SERVER
    unreadable = {**inside, "tool_input": {"command": "no markers"}}
    assert local_decisions.decide(unreadable, policy, contract)[0] == local_decisions.SERVER


def test_ask_is_a_deny_under_codex():
    ask = {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "ask",
                                  "permissionDecisionReason": "Pushing needs approval."}}
    denied = codex_hook_input.without_ask(ask)
    assert denied["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert "cannot ask" in denied["hookSpecificOutput"]["permissionDecisionReason"]
    assert codex_hook_input.without_ask(None) is None and codex_hook_input.is_deny(denied)
    assert codex_hook_input.in_codex({"OCTRYX_ENGINE": "codex"}) and not codex_hook_input.in_codex({})


def test_the_platforms_mcp_tools_keep_their_platform_name_in_the_hooks():
    call = {"tool_name": "mcp__octryx_knowledge__workflow_run_status", "tool_input": {}}
    assert codex_hook_input.split_apply_patch(call)[0]["tool_name"] == "mcp__octryx-knowledge__workflow_run_status"
    assert codex_hook_input.split_apply_patch({"tool_name": "Bash"})[0]["tool_name"] == "Bash"


def test_a_shell_apply_patch_is_decided_per_file_like_the_tool(tmp_path):
    """Codex patches with ``apply_patch <<'EOF'`` in the shell for a model it offers no patch tool (Gemma via
    LiteLLM): the hook decides it per file like the tool, never as a shell write."""
    root = tmp_path / "repo"
    (root / "docs").mkdir(parents=True)
    script = "apply_patch <<'PATCH'\n*** Begin Patch\n*** Add File: docs/SPEC.md\n+# Spec\n*** End Patch\nPATCH"
    call = {"tool_name": "Bash", "cwd": str(root), "tool_input": {"command": script}}
    parts = codex_hook_input.split_apply_patch(call)
    assert [(part["tool_name"], part["tool_input"]["file_path"]) for part in parts] == [
        ("Write", str(root / "docs/SPEC.md"))]
    import shlex

    wrapped = {**call, "tool_input": {"command": f"/bin/zsh -lc {shlex.quote(script)}"}}
    assert codex_hook_input.split_apply_patch(wrapped)[0]["tool_name"] == "Write"
    shell = {**call, "tool_input": {"command": "cat x > y"}}
    assert codex_hook_input.split_apply_patch(shell)[0]["tool_name"] == "Bash"
    assert codex_hook_input.shell_patch("echo '*** Begin Patch *** End Patch'") == ""  # not an apply_patch call


def test_a_broken_patch_is_answered_with_the_patch_format():
    """A broken ``apply_patch {"command": [...]}`` with ``*** Create File`` is denied with the exact form to use, not as
    an unclassified tool."""
    broken = ('apply_patch {"command":["apply_patch","*** Begin Patch\\n*** Create File: SPEC.md\\n# S\\n'
              '*** End Patch"]}')
    assert codex_hook_input.unreadable_patch({"tool_name": "Bash", "tool_input": {"command": broken}})
    bare = {"tool_name": "Bash", "tool_input": {"command": "/bin/zsh -lc apply_patch"}}
    assert codex_hook_input.unreadable_patch(bare)
    assert codex_hook_input.unreadable_patch({"tool_name": "apply_patch", "tool_input": {"command": "nonsense"}})
    good = "apply_patch <<'PATCH'\n*** Begin Patch\n*** Add File: SPEC.md\n+# S\n*** End Patch\nPATCH"
    assert not codex_hook_input.unreadable_patch({"tool_name": "Bash", "tool_input": {"command": good}})
    assert not codex_hook_input.unreadable_patch({"tool_name": "Bash", "tool_input": {"command": "cat README.md"}})
    assert "*** Add File:" in codex_hook_input.PATCH_FORMAT and "<<'PATCH'" in codex_hook_input.PATCH_FORMAT


def test_view_image_is_decided_as_a_read_and_codex_sub_agents_are_on(tmp_path):
    """View_image and spawn_agent were denied as unclassified tools, a model round each. Alice
    : allow by default, block as an admin option; the platform allows unknown tools, sub-agents are on."""
    call = {"tool_name": "view_image", "cwd": "/repo", "tool_input": {"path": "shots/home.png"}}
    assert codex_hook_input.split_apply_patch(call) == [
        {**call, "tool_name": "Read", "tool_input": {"file_path": "/repo/shots/home.png", "codex_tool": "view_image"}}]
    config = tomllib.loads(codex_config.config_toml(base_url="https://p.test", headers={}, model="m", wrapper="/w",
                                                    sandboxed=False))
    assert config["features"]["multi_agent"] is True and config["features"]["hooks"] is True


def test_a_phase_that_opted_in_gets_the_same_browser_server_in_codex(tmp_path):
    """Codex gets the Playwright MCP server of a Claude Code turn, with
    its restrictions, only when the phase opted in; its own hosted web search stays off."""
    prepared = _prepared(tmp_path)
    plain = tomllib.loads(codex_driver.prepare_home(prepared, sandboxed=False).joinpath("config.toml").read_text())
    assert set(plain["mcp_servers"]) == {"octryx_knowledge"}  # not opted in: unchanged
    prepared.extra["browser_mcp"] = BROWSER_SPEC
    config = tomllib.loads(codex_driver.prepare_home(prepared, sandboxed=False).joinpath("config.toml").read_text())
    server = config["mcp_servers"]["playwright"]
    assert server["command"] == BROWSER_SPEC["command"] and server["args"] == BROWSER_SPEC["args"]
    assert server["env"] == BROWSER_SPEC["env"] and server["default_tools_approval_mode"] == "approve"
    assert config["web_search"] == "disabled" and config["features"]["multi_agent"] is True
    terminal = tomllib.loads(codex_driver.prepare_home(prepared, sandboxed=True, interactive=True).joinpath(
        "config.toml").read_text())
    assert "playwright" not in terminal["mcp_servers"]  # the person's own terminal session: no run browser


@pytest.mark.parametrize(("url", "allowed"), [
    ("http://127.0.0.1:8765/", True), ("http://localhost:3000/menu?x=1", True),
    ("https://example.com/", False), ("http://10.0.0.5:8765/", False), ("file:///etc/passwd", False),
    ("http://127.0.0.1:24600/api/v1/agent-gateway", False),  # the platform's own port on a local stack
])
def test_codex_browser_calls_are_decided_like_claude_codes(url, allowed, monkeypatch):

    monkeypatch.setenv("OCTRYX_BASE_URL", "http://127.0.0.1:24600")
    hook_input = {"tool_name": "mcp__playwright__browser_navigate", "tool_input": {"url": url}, "cwd": "/repo"}
    parts = codex_hook_input.split_apply_patch(hook_input)
    assert [part["tool_name"] for part in parts] == ["mcp__playwright__browser_navigate"]  # Codex shows the same name
    # every session, after the platform's decision
    assert (pre_tool_use_hook.browser_refusal(parts[0]) is None) is allowed
    assert (browser_rules.browser_rule(parts[0]["tool_name"], parts[0]["tool_input"]) is None) is allowed  # local ones


@pytest.mark.parametrize(("url", "allowed"), [
    ("https://docs.python.org/3/", True), ("http://127.0.0.1:8765/", True), ("http://93.184.215.14/", True),
    ("http://10.0.0.5/", False), ("http://169.254.169.254/latest/meta-data", False), ("http://100.64.1.1/", False),
    ("http://[fd00::1]/", False), ("http://[::ffff:192.168.1.1]/", False), ("http://wiki.corp/", False),
    ("http://build.internal/", False), ("http://intranet/", False), ("http://0x7f.1/", False),
    ("https://platform.example/api", False), ("http://127.0.0.1:24600/", False),
    ("file:///etc/passwd", False), ("javascript:alert(1)", False), ("data:text/html,x", False),
])
def test_a_browser_with_external_pages_reads_public_hosts_only(url, allowed):
    """B13 (allow by default, block as an admin option): with the offer's ``browser_external`` the
    browser reads public http(s) pages; internal hosts, the platform and other schemes stay refused."""
    tool = "mcp__playwright__browser_navigate"
    platform = "https://platform.example" if "platform.example" in url else "http://127.0.0.1:24600"
    assert (browser_rules.browser_rule(tool, {"url": url}, platform_url=platform, external=True) is None) is allowed
    if "127.0.0.1" not in url:  # without the flag: loopback only
        assert browser_rules.browser_rule(tool, {"url": url}, platform_url=platform, external=False) is not None
