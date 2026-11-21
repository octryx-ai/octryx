"""Shared prepared-turn helper for the plain claude -p driver tests."""

from __future__ import annotations

from pathlib import Path

from octryx_claude.device_session import PreparedSession


def _prepared(tmp_path: Path, cli: str = "claude", **extra) -> PreparedSession:
    return PreparedSession(session_key="00000000-0000-4000-8000-0000000000dd", cli_path=cli,
                           settings_path=tmp_path / "settings.json", mcp_path=tmp_path / "mcp.json",
                           env={"CLAUDE_CODE_DISABLE_BACKGROUND_TASKS": "1", "X": "1"}, profile="seat",
                           model="claude-haiku-5-5",
                           extra={"lean": True, "workflow_run": True, "subagents": True, "plain": True,
                                  "permission_mode": "bypassPermissions", "context_window": 200000, **extra})
