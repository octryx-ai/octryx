"""Codex hook input in the shapes the launcher's hooks and the platform know (standard library only: the fast hook
imports it before the launcher)."""

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


# Codex patches in the shell for a model it offers no ``apply_patch`` tool.
def shell_patch(command: str) -> str:
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
    given = hook_input.get("tool_input") if isinstance(hook_input.get("tool_input"), dict) else {}
    if hook_input.get("tool_name") == APPLY_PATCH:
        return not patch_paths(str(given.get("command") or ""))
    if hook_input.get("tool_name") == "Bash":
        command = str(given.get("command") or "")
        return _first_word(command) == APPLY_PATCH and not patch_paths(shell_patch(command))
    return False


# Decided as a Read: a denial after every screenshot would cost a model round each time.
def _as_read(hook_input: dict[str, Any]) -> dict[str, Any]:
    given = hook_input.get("tool_input") if isinstance(hook_input.get("tool_input"), dict) else {}
    path = str(given.get("path") or "")
    cwd = str(hook_input.get("cwd") or "")
    absolute = path if posixpath.isabs(path) else posixpath.normpath(posixpath.join(cwd or "/", path))
    return {**hook_input, "tool_name": "Read", "tool_input": {"file_path": absolute, "codex_tool": "view_image"}}


def split_apply_patch(hook_input: dict[str, Any]) -> list[dict[str, Any]]:
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


# Codex hooks know only allow and deny; an ``ask`` would let the call run.
def without_ask(output: dict[str, Any] | None) -> dict[str, Any] | None:
    specific = (output or {}).get("hookSpecificOutput") if isinstance(output, dict) else None
    if not isinstance(specific, dict) or specific.get("permissionDecision") != "ask":
        return output
    reason = str(specific.get("permissionDecisionReason") or "").strip()
    return {**output, "hookSpecificOutput": {**specific, "permissionDecision": "deny",
                                             "permissionDecisionReason": f"{ASK_DENIED} {reason}".strip()[:600]}}


def guarded(environ: Any = None) -> bool:
    from .codex_hook_guard import GUARDED_ENV  # noqa: PLC0415

    return str((os.environ if environ is None else environ).get(GUARDED_ENV) or "") == "1"


ALLOW = {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "allow"}}


def decided(output: dict[str, Any] | None) -> dict[str, Any]:
    # The hook guard (``codex_hook_guard``) lets a call run only on an explicit allow.
    specific = (output or {}).get("hookSpecificOutput") if isinstance(output, dict) else None
    if isinstance(specific, dict) and specific.get("permissionDecision") in ("allow", "deny"):
        return output  # type: ignore[return-value]
    merged = {"hookEventName": "PreToolUse", **(specific if isinstance(specific, dict) else {}),
              "permissionDecision": "allow"}
    return {**(output or {}), "hookSpecificOutput": merged}


__all__ = [
    "PATCH_FORMAT",
    "shell_patch",
    "unreadable_patch",
    "APPLY_PATCH",
    "CODEX",
    "CODEX_MCP_SERVER",
    "ENGINE_ENV",
    "ALLOW",
    "decided",
    "guarded",
    "in_codex",
    "is_deny",
    "patch_paths",
    "platform_tool_name",
    "split_apply_patch",
    "without_ask",
]
