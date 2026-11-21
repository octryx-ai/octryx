"""Admin MCP surface: the governed registry operations (``app.services.mcp_server_registry_*``) under their
admin names, plus the stdio command bounds and the redacting runtime projection."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import HTTPException

_MAX_MCP_COMMAND_CHARS = 220
_MAX_MCP_ARG_CHARS = 500
_MAX_MCP_ARGS = 40
_UNSAFE_SHELL_EXECUTABLES = {"bash", "cmd", "powershell", "pwsh", "sh", "zsh"}
_SHELL_CONTROL_TOKENS = ("&&", "||", ";", "|", "`", "$(", "\n", "\r")

__all__ = ["serialize_mcp_server", "validate_mcp_extension_command"]


def _transport_value(config: Any) -> str:
    transport = getattr(config, "transport", "")
    return str(transport.value if hasattr(transport, "value") else transport)


def _contains_shell_control(value: Any) -> bool:
    text = str(value or "")
    return any(token in text for token in _SHELL_CONTROL_TOKENS)


def validate_mcp_extension_command(config: Any) -> None:
    """Reject unbounded shell-style MCP stdio execution."""
    if _transport_value(config) != "stdio":
        return
    command = str(getattr(config, "command", "") or "").strip()
    args = [str(arg) for arg in (getattr(config, "args", []) or [])]
    if not command:
        raise HTTPException(status_code=400, detail="stdio MCP servers require a command")
    if len(command) > _MAX_MCP_COMMAND_CHARS:
        raise HTTPException(status_code=400, detail="MCP command is too long")
    if len(args) > _MAX_MCP_ARGS:
        raise HTTPException(status_code=400, detail="MCP command has too many arguments")
    if any(len(arg) > _MAX_MCP_ARG_CHARS for arg in args):
        raise HTTPException(status_code=400, detail="MCP command argument is too long")
    if Path(command).name.lower() in _UNSAFE_SHELL_EXECUTABLES:
        raise HTTPException(status_code=400, detail="Shell-style MCP execution is not allowed")
    if _contains_shell_control(command) or any(_contains_shell_control(arg) for arg in args):
        raise HTTPException(status_code=400, detail="Shell control tokens are not allowed in MCP command configuration")


def serialize_mcp_server(config: Any, connected: bool, tool_count: int) -> dict[str, Any]:
    """Serialize runtime state through the existing redacting public projection."""
    metadata = dict(getattr(config, "metadata", {}) or {})
    public_config = config.to_public_dict() if hasattr(config, "to_public_dict") else {}
    return {
        "name": config.name,
        "command": config.command,
        "args": config.args,
        "transport": config.transport.value if hasattr(config.transport, "value") else config.transport,
        "url": config.url,
        "description": config.description,
        "auto_start": config.auto_start,
        "connected": connected,
        "tool_count": tool_count,
        "catalog_slug": metadata.get("catalog_slug"),
        "vendor": metadata.get("vendor"),
        "source_url": metadata.get("source_url"),
        "env": public_config.get("env", {}),
        "headers": public_config.get("headers", {}),
        "oauth": public_config.get("oauth"),
    }
