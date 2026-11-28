"""The shared act table as the hook bodies each engine's launcher sends to the platform."""

from __future__ import annotations

import json
import posixpath
from pathlib import Path
from typing import Any

from app.services.agent_gateway.engine_keys import ENGINE_CODEX, SESSION_ENGINE_KEY
from tests.workflow_run_octryx_support import ROOT

CLAUDE, CODEX = "claude", "codex"
ENGINES = (CLAUDE, CODEX)
SCENARIOS: list[dict[str, Any]] = json.loads((Path(__file__).parent / "scenarios.json").read_text())["scenarios"]
EXISTING = frozenset({"src/app.py"})
_MARKERS = (("*** Add File: ", "Write"), ("*** Update File: ", "Edit"), ("*** Delete File: ", "Edit"),
            ("*** Move to: ", "Write"))
_CODEX_MCP, _PLATFORM_MCP = "mcp__octryx_knowledge__", "mcp__octryx-knowledge__"


def tag(session, engine: str) -> None:
    if engine == CODEX:  # what the presence route stores for a launcher registering with engine codex
        session.metadata_ = {**dict(session.metadata_ or {}), SESSION_ENGINE_KEY: ENGINE_CODEX}


def _absolute(path: str) -> str:
    return path if posixpath.isabs(path) else posixpath.normpath(posixpath.join(ROOT, path))


# The launcher's workflow_run_facts for a file call: they follow the path, never the engine.
def _with_facts(hook: dict[str, Any]) -> dict[str, Any]:
    path = str(hook["tool_input"].get("file_path") or "")
    if not path:
        return hook
    relative = posixpath.relpath(path, ROOT)
    return {**hook, "workflow_run_facts": {"target_exists": relative in EXISTING, "shadows_installed": False}}


def _hook(name: str, tool_input: dict[str, Any]) -> dict[str, Any]:
    return _with_facts({"hook_event_name": "PreToolUse", "tool_name": name, "cwd": ROOT, "tool_input": tool_input})


def claude_bodies(act: dict[str, Any]) -> list[dict[str, Any]]:
    given = dict(act["tool_input"])
    if "file_path" in given:  # Claude Code names files by absolute path
        given["file_path"] = _absolute(given["file_path"])
    return [_hook(act["tool_name"], given)]


# Mirrors codex_hook_input.split_apply_patch (the backend cannot import the launcher); the launcher's conformance
# tests (clients/octryx-claude/tests/test_engine_conformance.py) prove both reach the platform as this same body.
def codex_bodies(act: dict[str, Any]) -> list[dict[str, Any]]:
    name, given = act["tool_name"], act["tool_input"]
    if name == "view_image":
        return [_hook("Read", {"file_path": _absolute(given["path"]), "codex_tool": "view_image"})]
    command = str(given.get("command") or "")
    if name == "Bash" and command.startswith("apply_patch") and "*** Begin Patch" in command:
        name, command = "apply_patch", command[command.index("*** Begin Patch"):]
    if name == "apply_patch":
        return [_hook(tool, {"file_path": _absolute(line[len(marker):].strip()), "codex_patch": True})
                for line in command.splitlines() for marker, tool in _MARKERS if line.startswith(marker)]
    if name.startswith(_CODEX_MCP):
        name = _PLATFORM_MCP + name[len(_CODEX_MCP):]
    return [_hook(name, dict(given))]


BODIES = {CLAUDE: claude_bodies, CODEX: codex_bodies}
