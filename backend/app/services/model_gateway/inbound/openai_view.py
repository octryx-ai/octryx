"""An Anthropic-shaped view of an OpenAI Responses request, for budget, logs and transcript only."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from typing import Any

ROLE_USER = "user"
ROLE_ASSISTANT = "assistant"
ROLE_SYSTEM = "system"
_TEXT_PARTS = frozenset({"input_text", "output_text", "text"})
_SYSTEM_ROLES = frozenset({"developer", "system"})
_TOOL_CALLS = frozenset({"function_call", "custom_tool_call", "local_shell_call"})
_TOOL_OUTPUTS = frozenset({"function_call_output", "custom_tool_call_output", "local_shell_call_output"})
_SKIPPED = frozenset({"reasoning", "compaction", "compaction_summary"})
LOCAL_SHELL_TOOL = "local_shell"


def is_responses_body(body: Any) -> bool:
    return isinstance(body, dict) and isinstance(body.get("input"), str | list)


def _type(item: Mapping[str, Any]) -> str | None:
    kind = item.get("type")
    return kind if isinstance(kind, str) else None


def _text_blocks(content: Any) -> list[dict[str, Any]]:
    if isinstance(content, str):
        return [{"type": "text", "text": content}] if content else []
    blocks: list[dict[str, Any]] = []
    for part in content if isinstance(content, list) else []:
        if isinstance(part, Mapping) and _type(part) in _TEXT_PARTS and isinstance(part.get("text"), str):
            blocks.append({"type": "text", "text": part["text"]})
    return blocks


def _tool_input(item: Mapping[str, Any]) -> dict[str, Any]:
    kind = item.get("type")
    if kind == "local_shell_call":
        action = item.get("action")
        return dict(action) if isinstance(action, Mapping) else {}
    raw = item.get("arguments") if kind == "function_call" else item.get("input")
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
        except ValueError:
            parsed = None
        return dict(parsed) if isinstance(parsed, Mapping) else {"input": raw}
    return dict(raw) if isinstance(raw, Mapping) else {}


# Codex's own tool names -> the names the platform's evidence, gates and counters read (Claude Code's), so a Codex
# session's shell command and file change count like a Claude Code session's (otherwise the spec-writing draft
# phase never sees "the specification file was written" under Codex).
CODEX_SHELL_TOOLS = frozenset({"exec_command", "shell", "shell_command", LOCAL_SHELL_TOOL})
CODEX_PATCH_TOOL = "apply_patch"


CODEX_MCP_PREFIX = "mcp__octryx_knowledge__"
PLATFORM_MCP_PREFIX = "mcp__octryx-knowledge__"


def _shell_patch(script: str) -> str:
    start, end = script.find("*** Begin Patch"), script.find("*** End Patch")
    head = script[:start] if start >= 0 else ""
    if start < 0 or end < start or "<<" not in head or "apply_patch" not in head.split("<<")[0]:
        return ""
    patch = script[start:end + len("*** End Patch")]
    return patch if re.search(r"^\*\*\* (Add|Update|Delete) File: \S", patch, re.MULTILINE) else ""


def evidence_names(name: str, tool_input: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    from ...agent_gateway.shell_read import unwrap

    if name.startswith(CODEX_MCP_PREFIX):  # Codex shows the server without "-"
        return PLATFORM_MCP_PREFIX + name.removeprefix(CODEX_MCP_PREFIX), tool_input
    if name == "view_image":  # Codex reads one image file: the launcher decides it as Read of that path
        return "Read", {"file_path": str(tool_input.get("path") or "")}
    if name in CODEX_SHELL_TOOLS:
        raw = tool_input.get("cmd") or tool_input.get("command")
        command = " ".join(str(part) for part in raw) if isinstance(raw, list) else str(raw or "")
        script = unwrap(command)
        if _shell_patch(script):  # ``apply_patch <<'EOF'`` in the shell: a file change, recorded as the tool
            return evidence_names(CODEX_PATCH_TOOL, {"input": _shell_patch(script)})
        return "Bash", {**tool_input, "command": script}
    if name == CODEX_PATCH_TOOL:
        patch = str(tool_input.get("input") or tool_input.get("patch") or tool_input.get("command") or "")
        path = next((line.split(": ", 1)[1].strip() for line in patch.splitlines()
                     if line.startswith(("*** Add File: ", "*** Update File: ", "*** Delete File: "))), "")
        return "Edit", {**tool_input, **({"file_path": path} if path else {})}
    return name, tool_input


def _tool_use(item: Mapping[str, Any]) -> dict[str, Any]:
    name = LOCAL_SHELL_TOOL if item.get("type") == "local_shell_call" else str(item.get("name") or "")
    if item.get("namespace"):  # a call of a namespace tool (an MCP server's): ``<namespace>__<name>``
        name = f"{item['namespace']}__{name}"
    name, tool_input = evidence_names(name, _tool_input(item))
    return {"type": "tool_use", "id": str(item.get("call_id") or item.get("id") or ""), "name": name,
            "input": tool_input}


# Codex reports a hook denial and a shell's exit status only as text (a Responses tool output has no error flag):
# without reading it a denied ``apply_patch`` is recorded as a successful Edit and the phase asks for a test run.
_CODEX_BLOCKED = "Command blocked by PreToolUse hook"
_CODEX_EXIT = re.compile(r"^Process exited with code (-?\d+)\s*$", re.MULTILINE)


def _failed(output: Any) -> bool:
    text = output if isinstance(output, str) else ""
    if text.lstrip().startswith(_CODEX_BLOCKED):
        return True
    status = _CODEX_EXIT.search(text[:400])
    return bool(status) and status.group(1) != "0"


def _tool_result(item: Mapping[str, Any]) -> dict[str, Any]:
    output = item.get("output")
    if isinstance(output, Mapping):  # an output object of its own (e.g. ``{"output": ..., "metadata": ...}``)
        output = output.get("output") if isinstance(output.get("output"), str | list) else json.dumps(output)
    block = {"type": "tool_result", "tool_use_id": str(item.get("call_id") or ""), "content": _text_blocks(output)}
    return {**block, "is_error": True} if _failed(output) else block


def _item_message(item: Any) -> tuple[str, list[dict[str, Any]]] | None:
    if not isinstance(item, Mapping):
        return None
    kind = _type(item)
    if kind in _SKIPPED:
        return None
    if kind == "message" or (kind is None and "role" in item):
        role = str(item.get("role") or "")
        blocks = _text_blocks(item.get("content"))
        if role in _SYSTEM_ROLES:
            return ROLE_SYSTEM, blocks
        return (role, blocks) if role in (ROLE_USER, ROLE_ASSISTANT) else (ROLE_SYSTEM, blocks)
    if kind in _TOOL_CALLS:
        return ROLE_ASSISTANT, [_tool_use(item)]
    if kind in _TOOL_OUTPUTS:
        return ROLE_USER, [_tool_result(item)]
    return ROLE_SYSTEM, [{"type": "text", "text": json.dumps(item, ensure_ascii=False, default=str)}]


def view_messages(raw_input: Any) -> list[dict[str, Any]]:
    if isinstance(raw_input, str):
        return [{"role": ROLE_USER, "content": _text_blocks(raw_input)}]
    messages: list[dict[str, Any]] = []
    for item in raw_input if isinstance(raw_input, list) else []:
        mapped = _item_message(item)
        if mapped is None or not mapped[1]:
            continue
        role, blocks = mapped
        if messages and messages[-1]["role"] == role:
            messages[-1]["content"].extend(blocks)
        else:
            messages.append({"role": role, "content": list(blocks)})
    return messages


def view_tools(tools: Any) -> list[dict[str, str]]:
    names = []
    for tool in tools if isinstance(tools, list) else []:
        if isinstance(tool, Mapping):
            names.append({"name": str(tool.get("name") or tool.get("type") or "")})
    return names


def anthropic_view(body: Mapping[str, Any]) -> dict[str, Any]:
    view: dict[str, Any] = {
        "model": body.get("model"),
        "messages": view_messages(body.get("input")),
        "stream": body.get("stream") is True,
    }
    instructions = body.get("instructions")
    if isinstance(instructions, str) and instructions:
        view["system"] = instructions
    tools = view_tools(body.get("tools"))
    if tools:
        view["tools"] = tools
    max_output = body.get("max_output_tokens")
    if isinstance(max_output, int) and not isinstance(max_output, bool) and max_output > 0:
        view["max_tokens"] = max_output
    return view


__all__ = ["LOCAL_SHELL_TOOL", "anthropic_view", "is_responses_body", "view_messages", "view_tools"]
