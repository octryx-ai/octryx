"""Shared helpers for the test_local_tests_* modules."""

from __future__ import annotations

SHIM = "/Users/u/.local/bin/octryx-claude"


PHASE = {"digest": "d", "phase": {"node_id": "implement", "capability_class": "change"}}


def _hook_input(command: str) -> dict:
    return {"hook_event_name": "PreToolUse", "tool_name": "Bash", "cwd": "/repo",
            "tool_input": {"command": command, "description": "run the tests"}}
