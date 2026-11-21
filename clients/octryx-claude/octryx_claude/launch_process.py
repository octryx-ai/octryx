"""Starting the Claude Code process: refused flags, its argv, the scrubbed environment lists, the session files."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any

from .state import write_private_json

PROFILE_GOVERNED = "governed"
PROFILE_SEAT = "seat"
PROFILES = (PROFILE_GOVERNED, PROFILE_SEAT)

# Credentials and provider switches that would take traffic away from the gateway.
SCRUBBED_ENV = (
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_AUTH_TOKEN",
    "ANTHROPIC_PROFILE",
    "ANTHROPIC_AWS_API_KEY",
    "ANTHROPIC_AWS_BASE_URL",
    "ANTHROPIC_BEDROCK_BASE_URL",
    "ANTHROPIC_BEDROCK_MANTLE_BASE_URL",
    "ANTHROPIC_FOUNDRY_API_KEY",
    "ANTHROPIC_FOUNDRY_AUTH_TOKEN",
    "ANTHROPIC_FOUNDRY_BASE_URL",
    "ANTHROPIC_VERTEX_BASE_URL",
    "AWS_BEARER_TOKEN_BEDROCK",
    "CLAUDE_CODE_OAUTH_TOKEN",
    "CLAUDE_CODE_OAUTH_REFRESH_TOKEN",
    "CLAUDE_CODE_PROVIDER_MANAGED_BY_HOST",
    "CLAUDE_CODE_SKIP_ANTHROPIC_AWS_AUTH",
    "CLAUDE_CODE_SKIP_BEDROCK_AUTH",
    "CLAUDE_CODE_SKIP_FOUNDRY_AUTH",
    "CLAUDE_CODE_SKIP_MANTLE_AUTH",
    "CLAUDE_CODE_SKIP_VERTEX_AUTH",
)
# Provider selection. Also blanked in the settings ``env`` (an empty value counts as
# unset for provider selection), so a project settings file cannot switch it back on.
PROVIDER_SWITCHES = (
    "CLAUDE_CODE_USE_ANTHROPIC_AWS",
    "CLAUDE_CODE_USE_BEDROCK",
    "CLAUDE_CODE_USE_FOUNDRY",
    "CLAUDE_CODE_USE_MANTLE",
    "CLAUDE_CODE_USE_VERTEX",
)

# User flags that would bypass hooks, replace the generated settings/MCP config or
# leave the local, governed session. Refused explicitly.
REFUSED_FLAGS = (
    "--allow-dangerously-skip-permissions",
    "--bare",
    "--bg",
    "--background",
    "--cloud",
    "--dangerously-skip-permissions",
    "--mcp-config",
    # A foreign plugin could bring hooks that run outside the tool check; catalog skills come
    # through the launcher's own per-session plugin.
    "--plugin-dir",
    "--remote-control",
    "--safe-mode",
    "--setting-sources",
    "--settings",
    "--strict-mcp-config",
    "--teleport",
)
_RESUME_FLAGS = ("-c", "--continue", "-r", "--resume", "--from-pr", "--session-id")


class LaunchRefusedError(Exception):
    """The session is not started. ``code`` is fixed; ``detail`` names a flag at most."""

    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(code)
        self.code = code
        self.detail = detail


def _flag_name(arg: str) -> str:
    return arg.split("=", 1)[0]


def build_claude_argv(claude: str, *, settings_path: Path, mcp_path: Path, session_key: str,
                      user_args: Sequence[str], plugin_dir: Path | None = None) -> list[str]:
    names = [_flag_name(arg) for arg in user_args if arg.startswith("-")]
    for name in names:
        if name in REFUSED_FLAGS:
            raise LaunchRefusedError("flag_not_allowed", name)
    argv = [claude, "--settings", str(settings_path), "--strict-mcp-config", "--mcp-config", str(mcp_path)]
    if plugin_dir is not None:
        argv += ["--plugin-dir", str(plugin_dir)]
    if not any(name in _RESUME_FLAGS for name in names):
        # Claude's own session id equals the gateway session key: one id end to end.
        argv += ["--session-id", session_key]
    return argv + list(user_args)


def write_session_files(session_dir: Path, settings: dict[str, Any], mcp: dict[str, Any]) -> tuple[Path, Path]:
    settings_path = session_dir / "settings.json"
    mcp_path = session_dir / "mcp.json"
    write_private_json(settings_path, settings)
    write_private_json(mcp_path, mcp)
    return settings_path, mcp_path
