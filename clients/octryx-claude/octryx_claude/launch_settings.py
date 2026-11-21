"""The generated per-session settings and MCP config of Claude Code.

The ``--settings`` file (command-line settings outrank project, local and user settings) pins the session env,
the ``apiKeyHelper`` (governed profile only), the permission rules of the Workspace policy, the sandbox, the
company models of the ``/model`` picker and the octryx hooks; ``--strict-mcp-config`` leaves only the Octryx
knowledge MCP and the catalog servers the Workspace allows.
"""

from __future__ import annotations

import os
import shlex
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from . import model_picker
from .launch_process import PROFILE_GOVERNED, PROFILE_SEAT
from .launch_sandbox import sandbox_settings

KNOWLEDGE_MCP_PATH = "/api/v1/mcp/knowledge-protocol/mcp"
MCP_SERVER_NAME = "octryx-knowledge"
MAX_POLICY_RULES = 200
MAX_RULE_CHARS = 300

# Hook timeouts (seconds). Each exceeds the HTTP timeout of its hook, so a slow
# platform yields the hook's own explicit answer instead of a Claude Code timeout.
PRE_TOOL_USE_HOOK_TIMEOUT = 20
# Stop and PostToolUse may run the automatic handoff (freeze 3c: git, push or bundle upload); normal calls stay fast.
# The Stop hook builds the pass's whole change (run_contract.CHANGE_GIT_TIMEOUT per git step) and posts it.
STOP_HOOK_TIMEOUT = 240
SESSION_END_HOOK_TIMEOUT = 30
# Seat only: records why a turn ended with an API error (Claude Code ignores this hook's output).
STOP_FAILURE_HOOK_TIMEOUT = 10
POST_TOOL_USE_HOOK_TIMEOUT = 120
# ``/handoff`` runs in UserPromptSubmit before any model call, and may poll the takeover for up to 60 s.
USER_PROMPT_SUBMIT_HOOK_TIMEOUT = 300
USER_PROMPT_EXPANSION_HOOK_TIMEOUT = 10
PRE_COMPACT_HOOK_TIMEOUT = 60  # the local decision model may start once to rank what is kept
SESSION_START_HOOK_TIMEOUT = 10
POST_COMPACT_HOOK_TIMEOUT = 40
# Every tool: execution evidence (test commands run through Bash, reads as a workflow phase's read evidence) and,
# since the tool-result content check
# (what a tool returned may be masked or kept out of the model by a content policy).
POST_TOOL_USE_MATCHER = "*"
NODE_PROXY_ENV = "NODE_USE_ENV_PROXY"


def _policy_rules(policy: Mapping[str, Any], key: str) -> list[str]:
    permissions = policy.get("permissions")
    values = permissions.get(key) if isinstance(permissions, Mapping) else None
    if not isinstance(values, list):
        return []
    rules = [value for value in values if isinstance(value, str) and 0 < len(value) <= MAX_RULE_CHARS]
    return rules[:MAX_POLICY_RULES]


def _command(shim: Path, *args: str) -> str:
    return " ".join(shlex.quote(part) for part in (str(shim), *args))


def _hook(command: str, timeout: int, matcher: str = "*") -> list[dict[str, Any]]:
    return [{"matcher": matcher, "hooks": [{"type": "command", "command": command, "timeout": timeout}]}]


def _session_hooks(shim: Path) -> dict[str, Any]:
    """The octryx hooks of a session; a failing PreToolUse hook denies the tool call (fail closed)."""
    pre_tool_use = (
        f"{_command(shim, 'hook', 'pre-tool-use')} || "
        "{ echo 'Octryx hook failed; tool call denied (fail closed).' >&2; exit 2; }"
    )
    post_tool_use = _command(shim, "hook", "post-tool-use")
    return {
        "PreToolUse": _hook(pre_tool_use, PRE_TOOL_USE_HOOK_TIMEOUT),
        "PostToolUse": _hook(post_tool_use, POST_TOOL_USE_HOOK_TIMEOUT, POST_TOOL_USE_MATCHER),
        "PostToolUseFailure": _hook(post_tool_use, POST_TOOL_USE_HOOK_TIMEOUT, POST_TOOL_USE_MATCHER),
        "Stop": _hook(_command(shim, "hook", "stop"), STOP_HOOK_TIMEOUT),
        "SubagentStop": _hook(_command(shim, "hook", "stop"), STOP_HOOK_TIMEOUT),
        "SessionEnd": _hook(_command(shim, "hook", "session-end"), SESSION_END_HOOK_TIMEOUT),
        "UserPromptSubmit": _hook(_command(shim, "hook", "user-prompt-submit"), USER_PROMPT_SUBMIT_HOOK_TIMEOUT),
        # A typed /octryx:<skill> is recorded by name (usage); never blocks.
        "UserPromptExpansion": _hook(_command(shim, "hook", "user-prompt-expansion"),
                                     USER_PROMPT_EXPANSION_HOOK_TIMEOUT),
        # The context manager decides what a compaction keeps and puts it back afterwards
        # (``context_manager``; ``octryx-claude context-manager off`` switches both off).
        "PreCompact": _hook(_command(shim, "hook", "pre-compact"), PRE_COMPACT_HOOK_TIMEOUT),
        "SessionStart": _hook(_command(shim, "hook", "session-start"), SESSION_START_HOOK_TIMEOUT, "compact"),
        # Lessons learned for the team (``session_lessons``; the Workspace decides, the Mac may opt out).
        "PostCompact": _hook(_command(shim, "hook", "post-compact"), POST_COMPACT_HOOK_TIMEOUT),
    }


def build_settings(*, shim: Path, state_root: Path, env: Mapping[str, str], policy: Mapping[str, Any],
                   base_url: str, profile: str = PROFILE_GOVERNED, plugin_dir: Path | None = None) -> dict[str, Any]:
    # The credential store is never readable or editable by the agent's file tools.
    protected = f"//{str(state_root).lstrip('/')}/**"
    deny = [f"Read({protected})", f"Edit({protected})", *_policy_rules(policy, "deny")]
    if os.environ.get("OCTRYX_SANDBOX_RUN_ID"):
        # A platform sandbox: the enrollment and git token files are never read by the agent's file tools (the
        # runner reads them itself before any turn; the PreToolUse hook and the tokens' scope are the other walls).
        deny += ["Read(//run/secrets/**)", "Edit(//run/secrets/**)"]
    if plugin_dir is not None:
        # The session's catalog skills are readable (Claude Code loads their references) but never editable.
        plugin = f"//{str(plugin_dir).lstrip('/')}/**"
        # Edit covers every file-writing tool; Claude Code reports a Write(...) rule as never matching.
        deny += [f"Edit({plugin})"]
    settings: dict[str, Any] = {
        # Node (fetch, npm scripts, Playwright's own downloads) ignores the sandbox's HTTP(S)_PROXY by default and its
        # DNS is blocked in the sandbox ("getaddrinfo ENOTFOUND"); with this it goes through the
        # sandbox's proxy. Outside the sandbox there is no proxy variable and nothing changes.
        "env": {**dict(env), NODE_PROXY_ENV: "1"},
        "permissions": {
            # The launcher's own Octryx MCP server only; scope and policy still decide.
            # Plus the Workspace's autonomy set: what the agent may run without asking.
            "allow": [f"mcp__{MCP_SERVER_NAME}", *_policy_rules(policy, "allow")],
            "deny": deny,
            "ask": _policy_rules(policy, "ask"),
        },
        "sandbox": sandbox_settings(state_root=state_root, base_url=base_url, policy=policy, shim=shim),
        "disableAllHooks": False,
        # `!`cmd`` blocks in any skill (catalog, project or personal) never run before the model sees them.
        "disableSkillShellExecution": True,
        "hooks": _session_hooks(shim),
    }
    picker = model_picker.model_picker_setting(model_picker.picker_rows(policy, profile))
    if picker is not None:
        settings["modelPicker"] = picker
    if profile == PROFILE_SEAT:
        # A rejected subscription login or a reached limit becomes an explicit message (``seat_status``).
        settings["hooks"]["StopFailure"] = _hook(_command(shim, "hook", "stop-failure"), STOP_FAILURE_HOOK_TIMEOUT)
    else:
        # A configured apiKeyHelper outranks a subscription login, so only the governed profile sets it.
        settings["apiKeyHelper"] = _command(shim, "api-key-helper")
    # The person chooses the permission mode, bypass included, as in plain Claude Code. The deny
    # rules above (credential store, policy) and the platform's PreToolUse check still run in every mode; a Workspace
    # can switch bypass off (``agent_gateway_policy.bypass_permissions = "disabled"``).
    permissions = policy.get("permissions") if isinstance(policy.get("permissions"), Mapping) else {}
    if permissions.get("bypass_permissions") == "disabled":
        settings["permissions"]["disableBypassPermissionsMode"] = "disable"
    return settings


def build_mcp_config(*, shim: Path, base_url: str,
                     catalog_servers: Mapping[str, dict[str, Any]] | None = None) -> dict[str, Any]:
    """The session's only MCP config (``--strict-mcp-config``): the knowledge server plus the catalog's MCP
    server entries the Workspace ``mcp_policy`` allows (image by digest, no shell variables passed through)."""
    servers: dict[str, Any] = {
        MCP_SERVER_NAME: {
            "type": "http",
            "url": f"{base_url}{KNOWLEDGE_MCP_PATH}",
            "headersHelper": _command(shim, "mcp-headers"),
        }
    }
    for name, spec in (catalog_servers or {}).items():
        if name != MCP_SERVER_NAME:
            servers[name] = dict(spec)
    return {"mcpServers": servers}
