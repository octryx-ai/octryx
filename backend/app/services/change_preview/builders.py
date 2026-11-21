"""Building the change preview a person sees for a command or a tool call."""

from __future__ import annotations

import shlex
from pathlib import Path
from typing import Any


def build_command_change_preview(tool_name: str, command: str | list[str], *, cwd: str | None = None) -> dict[str, Any]:
    command_text = " ".join(str(part) for part in command) if isinstance(command, list) else str(command or "")
    try:
        argv = command if isinstance(command, list) else shlex.split(command_text, posix=True)
    except ValueError:
        argv = [command_text]
    executable = Path(str(argv[0] if argv else "")).name.lower()
    category = "shell"
    title = "Command change preview"
    details: list[str] = []
    if executable == "terraform":
        category = "terraform"
        action = str(argv[1] if len(argv) > 1 else "command").strip() or "command"
        title = f"Terraform {action}"
        details.append(f"Terraform command `{action}` will run in `{cwd or '.'}`.")
    elif executable == "kubectl":
        category = "kubernetes"
        verb = str(argv[1] if len(argv) > 1 else "command").strip() or "command"
        title = f"Kubernetes {verb}"
        details.append(f"`kubectl {verb}` will run against the configured cluster context.")
    else:
        title = f"{tool_name} command"
        details.append("The approved command will execute exactly as shown below.")
    if cwd:
        details.append(f"Working directory: `{cwd}`")
    return {
        "kind": category,
        "title": title,
        "summary": command_text,
        "command": command_text,
        "cwd": cwd or "",
        "argv": [str(item) for item in argv],
        "details": details,
    }


async def build_tool_change_preview(tool_name: str, params: dict[str, Any], context: Any) -> dict[str, Any] | None:
    from ...tools.registry import TOOL_REGISTRY

    if str(tool_name or "").startswith("rest__"):
        # A custom REST operation is a database row, not a registry tool: its preview is the request it would send.
        from ..rest_connector.preview import rest_change_preview

        return await rest_change_preview(tool_name, params, context)
    tool = TOOL_REGISTRY.get(tool_name)
    preview = getattr(tool, "preview", None)
    if preview is None:
        return None
    payload = await preview(params, context)
    if not isinstance(payload, dict):
        return None
    payload.setdefault("toolName", tool_name)
    return payload
