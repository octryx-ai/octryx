"""Codex hook input in the shapes the launcher's hooks and the platform know (standard library only: the fast hook
imports it before the launcher).

Codex calls the same hooks as Claude Code with Claude-compatible JSON (``codex_driver``). Two things differ:

- **file edits** are one ``apply_patch`` call whose ``tool_input.command`` is the patch text, possibly touching
  several files. :func:`split_apply_patch` turns it into one ``Write`` (a new file) or ``Edit`` (a change, a move or a
  deletion) per path, each with an absolute ``file_path``. The PreToolUse decision allows the patch only when every
  part is allowed; the evidence records every part;
- **no ``ask``**: Codex's hooks know allow and deny only, and an ``ask`` would let the call run. In a Codex session
  (:data:`ENGINE_ENV` = ``codex``) an ``ask`` becomes a deny that says why (:func:`without_ask`).
"""

from __future__ import annotations

import os
import posixpath
from typing import Any

ENGINE_ENV = "OCTRYX_ENGINE"
CODEX = "codex"
APPLY_PATCH = "apply_patch"
# Codex names an MCP server's tools ``mcp__<server>__<tool>`` and allows no "-" in the server name it shows the
# model, so the platform's server is ``octryx_knowledge`` there; the hooks and the platform know it as
# ``octryx-knowledge``.
CODEX_MCP_SERVER = "octryx_knowledge"
PLATFORM_MCP_SERVER = "octryx-knowledge"
_MARKERS = (("*** Add File: ", "Write"), ("*** Update File: ", "Edit"), ("*** Delete File: ", "Edit"),
            ("*** Move to: ", "Write"))
ASK_DENIED = ("This call needs a person's approval, which a Codex session cannot ask for. "
              "Do it another way or leave it for the person.")


def in_codex(environ: Any = None) -> bool:
    return str((os.environ if environ is None else environ).get(ENGINE_ENV) or "") == CODEX


def patch_paths(patch: str) -> list[tuple[str, str]]:
    """``(tool, path)`` per file the patch touches, in order, each once."""
    seen: set[str] = set()
    found: list[tuple[str, str]] = []
    for line in str(patch or "").splitlines():
        for marker, tool in _MARKERS:
            if line.startswith(marker):
                path = line[len(marker):].strip()
                if path and path not in seen:
                    seen.add(path)
                    found.append((tool, path))
    return found


VIEW_IMAGE = "view_image"


def platform_tool_name(name: str) -> str:
    prefix = f"mcp__{CODEX_MCP_SERVER}__"
    return f"mcp__{PLATFORM_MCP_SERVER}__{name[len(prefix):]}" if name.startswith(prefix) else name


def shell_patch(command: str) -> str:
    """The patch of ``apply_patch <<'EOF' ... EOF`` run in the shell (how Codex patches files for a model it does not
    know and offers no ``apply_patch`` tool), possibly inside ``<shell> -lc '...'``; ``""`` for anything else."""
    text = str(command or "")
    start = text.find("*** Begin Patch")
    end = text.find("*** End Patch")
    head = text[:start] if start >= 0 else ""
    if start < 0 or end < start or "apply_patch" not in head.split("<<")[0]:
        return ""
    return text[start:end + len("*** End Patch")]


PATCH_FORMAT = ("Write files with apply_patch in the shell, exactly this form (one call per change, paths relative "
                "to the repository):\napply_patch <<'PATCH'\n*** Begin Patch\n*** Add File: docs/NEW.md\n+first line\n"
                "+second line\n*** Update File: src/app.py\n@@\n-old line\n+new line\n*** End Patch\nPATCH\n"
                "Every line of an added file starts with '+'. No JSON, no other markers (only Add File, Update File, "
                "Delete File).")


def _first_word(command: str) -> str:
    """The command's first word, inside Codex's ``<shell> -lc '<script>'`` wrapper too."""
    import shlex  # noqa: PLC0415

    try:
        words = shlex.split(command)
    except ValueError:
        words = command.split()
    if len(words) >= 3 and posixpath.basename(words[0]) in {"sh", "bash", "zsh", "dash"} and words[1].startswith("-") \
            and "c" in words[1]:
        script = words[2].strip().split(None, 1)
        return script[0] if script else ""
    return words[0] if words else ""


def unreadable_patch(hook_input: dict[str, Any]) -> bool:
    """An ``apply_patch`` call (the tool, or ``apply_patch`` run in the shell) that names no file it changes."""
    given = hook_input.get("tool_input") if isinstance(hook_input.get("tool_input"), dict) else {}
    if hook_input.get("tool_name") == APPLY_PATCH:
        return not patch_paths(str(given.get("command") or ""))
    if hook_input.get("tool_name") == "Bash":
        command = str(given.get("command") or "")
        return _first_word(command) == APPLY_PATCH and not patch_paths(shell_patch(command))
    return False


def _as_read(hook_input: dict[str, Any]) -> dict[str, Any]:
    """Codex's ``view_image`` reads one file: the platform decides it as ``Read`` of that path, never as an
    unclassified tool (a denial after every screenshot would waste a model round each time)."""
    given = hook_input.get("tool_input") if isinstance(hook_input.get("tool_input"), dict) else {}
    path = str(given.get("path") or "")
    cwd = str(hook_input.get("cwd") or "")
    absolute = path if posixpath.isabs(path) else posixpath.normpath(posixpath.join(cwd or "/", path))
    return {**hook_input, "tool_name": "Read", "tool_input": {"file_path": absolute, "codex_tool": "view_image"}}


def split_apply_patch(hook_input: dict[str, Any]) -> list[dict[str, Any]]:
    """One hook input per file of an ``apply_patch`` call; the platform's MCP tools under the platform's server
    name; any other call unchanged. A patch without a file it names (unreadable) stays one ``apply_patch`` call,
    which no local rule allows."""
    if hook_input.get("tool_name") == VIEW_IMAGE:
        return [_as_read(hook_input)]
    if hook_input.get("tool_name") == "Bash":
        given = hook_input.get("tool_input") if isinstance(hook_input.get("tool_input"), dict) else {}
        patch = shell_patch(str(given.get("command") or ""))
        if patch:  # the file change of a shell ``apply_patch``: decided per file like the tool
            hook_input = {**hook_input, "tool_name": APPLY_PATCH, "tool_input": {"command": patch}}
    if hook_input.get("tool_name") != APPLY_PATCH:
        name = str(hook_input.get("tool_name") or "")
        return [{**hook_input, "tool_name": platform_tool_name(name)} if name else hook_input]
    tool_input = hook_input.get("tool_input") if isinstance(hook_input.get("tool_input"), dict) else {}
    cwd = str(hook_input.get("cwd") or "")
    parts = []
    for tool, path in patch_paths(str(tool_input.get("command") or "")):
        absolute = path if posixpath.isabs(path) else posixpath.normpath(posixpath.join(cwd or "/", path))
        parts.append({**hook_input, "tool_name": tool, "tool_input": {"file_path": absolute, "codex_patch": True}})
    return parts or [hook_input]


def is_deny(output: dict[str, Any] | None) -> bool:
    specific = (output or {}).get("hookSpecificOutput") if isinstance(output, dict) else None
    return isinstance(specific, dict) and specific.get("permissionDecision") == "deny"


def without_ask(output: dict[str, Any] | None) -> dict[str, Any] | None:
    """In a Codex session, an ``ask`` decision is a deny (Codex would run the call)."""
    specific = (output or {}).get("hookSpecificOutput") if isinstance(output, dict) else None
    if not isinstance(specific, dict) or specific.get("permissionDecision") != "ask":
        return output
    reason = str(specific.get("permissionDecisionReason") or "").strip()
    return {**output, "hookSpecificOutput": {**specific, "permissionDecision": "deny",
                                             "permissionDecisionReason": f"{ASK_DENIED} {reason}".strip()[:600]}}


__all__ = [
    "PATCH_FORMAT",
    "shell_patch",
    "unreadable_patch",
    "APPLY_PATCH",
    "CODEX",
    "CODEX_MCP_SERVER",
    "ENGINE_ENV",
    "in_codex",
    "is_deny",
    "patch_paths",
    "platform_tool_name",
    "split_apply_patch",
    "without_ask",
]
