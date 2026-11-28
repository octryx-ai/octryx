"""One comparable key per Codex exec call: an inner occurrence and a hook report in the platform's names."""

from __future__ import annotations

import json
import posixpath
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from ...models import ToolCall
from .codex_exec_parser import ExecOccurrence

EXEC_CALL_KEY = "exec_call"
_PATCH_MARKERS = ("*** Add File: ", "*** Update File: ", "*** Delete File: ", "*** Move to: ")
_PATCH_TOOLS = frozenset({"Write", "Edit"})


def _parameters(row: ToolCall) -> dict[str, Any]:
    return row.parameters if isinstance(row.parameters, dict) else {}


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, default=str)


def _patch_paths(patch: str) -> tuple[str, ...]:
    return tuple(line[len(marker):].strip() for line in str(patch or "").splitlines() for marker in _PATCH_MARKERS
                 if line.startswith(marker) and line[len(marker):].strip())


def _command_key(command: Any) -> str:
    from ..model_gateway.inbound.transcript_tools import MAX_COMMAND_CHARS
    from ..redaction_policy import redact_secret_text
    from .shell_read import unwrap

    text = " ".join(str(part) for part in command) if isinstance(command, list) else str(command or "")
    return str(redact_secret_text(unwrap(text).strip(), max_chars=MAX_COMMAND_CHARS) or "").strip()


@dataclass(frozen=True, slots=True)
class _Call:
    tool: str
    command: str = ""
    paths: tuple[str, ...] = ()
    arguments: str = ""
    tool_input: Mapping[str, Any] = field(default_factory=dict)


def _occurrence_call(occurrence: ExecOccurrence) -> _Call | None:
    from ..model_gateway.inbound.openai_view import CODEX_PATCH_TOOL, evidence_names
    from ..model_gateway.inbound.transcript_tools import bounded_tool_input

    args = occurrence.args
    if isinstance(args, str):
        tool_input: dict[str, Any] = {"input": args}
    elif isinstance(args, Mapping):
        tool_input = dict(args)
    else:
        return None
    name, mapped = evidence_names(occurrence.name, tool_input)
    if name == "Bash":
        return _Call("Bash", command=_command_key(mapped.get("command")), tool_input=mapped)
    if name == "Edit" and occurrence.name in (CODEX_PATCH_TOOL, "exec_command", "shell", "shell_command"):
        patch = str(mapped.get("input") or mapped.get("patch") or mapped.get("command") or "")
        paths = _patch_paths(patch)
        return _Call("patch", paths=paths, tool_input=mapped) if paths else None
    return _Call(name, arguments=_canonical(bounded_tool_input(mapped)), tool_input=mapped)


def _hook_key(hook: ToolCall) -> tuple[str, str, str] | None:
    recorded = _parameters(hook).get(EXEC_CALL_KEY)
    if not isinstance(recorded, Mapping):
        return None
    tool = str(recorded.get("tool") or "")
    tool_input = recorded.get("input") if isinstance(recorded.get("input"), Mapping) else {}
    if tool == "Bash":
        return "Bash", _command_key(tool_input.get("command")), ""
    if tool in _PATCH_TOOLS and tool_input.get("file_path"):
        return "patch", posixpath.normpath(str(tool_input["file_path"])), str(recorded.get("cwd") or "/")
    return tool, _canonical(tool_input), ""


def _slot_matches(call: _Call, key: tuple[str, str, str]) -> bool:
    kind, value, cwd = key
    if call.tool == "Bash":
        return kind == "Bash" and bool(call.command) and value == call.command
    if call.tool == "patch":
        return kind == "patch" and any(posixpath.normpath(posixpath.join(cwd, path)) == value for path in call.paths)
    return kind == call.tool and value == call.arguments
