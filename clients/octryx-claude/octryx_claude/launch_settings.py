"""The generated per-session settings and MCP config of Claude Code."""

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

# Each hook timeout exceeds its HTTP timeout, so a slow platform gets the hook's answer, not a Claude Code timeout.
PRE_TOOL_USE_HOOK_TIMEOUT = 20
# The Stop hook builds and posts the pass's whole change (run_contract.CHANGE_GIT_TIMEOUT per git step).
STOP_HOOK_TIMEOUT = 240
SESSION_END_HOOK_TIMEOUT = 30
STOP_FAILURE_HOOK_TIMEOUT = 10
POST_TOOL_USE_HOOK_TIMEOUT = 120
# ``/handoff`` runs in UserPromptSubmit before any model call, and may poll the takeover for up to 60 s.
USER_PROMPT_SUBMIT_HOOK_TIMEOUT = 300
USER_PROMPT_EXPANSION_HOOK_TIMEOUT = 10
PRE_COMPACT_HOOK_TIMEOUT = 60  # the local decision model may start once to rank what is kept
SESSION_START_HOOK_TIMEOUT = 10
POST_COMPACT_HOOK_TIMEOUT = 40
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
        "UserPromptExpansion": _hook(_command(shim, "hook", "user-prompt-expansion"),
                                     USER_PROMPT_EXPANSION_HOOK_TIMEOUT),
        "PreCompact": _hook(_command(shim, "hook", "pre-compact"), PRE_COMPACT_HOOK_TIMEOUT),
        "SessionStart": _hook(_command(shim, "hook", "session-start"), SESSION_START_HOOK_TIMEOUT, "compact"),
        "PostCompact": _hook(_command(shim, "hook", "post-compact"), POST_COMPACT_HOOK_TIMEOUT),
    }


def build_settings(*, shim: Path, state_root: Path, env: Mapping[str, str], policy: Mapping[str, Any],
                   base_url: str, profile: str = PROFILE_GOVERNED, plugin_dir: Path | None = None) -> dict[str, Any]:
    protected = f"//{str(state_root).lstrip('/')}/**"
    deny = [f"Read({protected})", f"Edit({protected})", *_policy_rules(policy, "deny")]
    if os.environ.get("OCTRYX_SANDBOX_RUN_ID"):
        # The runner reads the enrollment and git token files itself before any turn.
        deny += ["Read(//run/secrets/**)", "Edit(//run/secrets/**)"]
    if plugin_dir is not None:
        # The session's catalog skills are readable (Claude Code loads their references) but never editable.
        plugin = f"//{str(plugin_dir).lstrip('/')}/**"
        # Edit covers every file-writing tool; Claude Code reports a Write(...) rule as never matching.
        deny += [f"Edit({plugin})"]
    settings: dict[str, Any] = {
        # Node ignores the sandbox's HTTP(S)_PROXY by default and its DNS is blocked there; this routes it through
        # the proxy. Outside the sandbox there is no proxy variable and nothing changes.
        "env": {**dict(env), NODE_PROXY_ENV: "1"},
        "permissions": {
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
        settings["hooks"]["StopFailure"] = _hook(_command(shim, "hook", "stop-failure"), STOP_FAILURE_HOOK_TIMEOUT)
    else:
        # A configured apiKeyHelper outranks a subscription login, so only the governed profile sets it.
        settings["apiKeyHelper"] = _command(shim, "api-key-helper")
    # The person chooses the permission mode, bypass included; the deny rules and PreToolUse check run in every mode.
    permissions = policy.get("permissions") if isinstance(policy.get("permissions"), Mapping) else {}
    if permissions.get("bypass_permissions") == "disabled":
        settings["permissions"]["disableBypassPermissionsMode"] = "disable"
    return settings


def build_mcp_config(*, shim: Path, base_url: str,
                     catalog_servers: Mapping[str, dict[str, Any]] | None = None) -> dict[str, Any]:
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
