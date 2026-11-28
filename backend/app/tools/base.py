"""Base Tool interface and result type."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from .tool_names import READONLY_TOOL_NAMES, ToolName


@dataclass(frozen=True)
class ToolResult:
    data: dict[str, Any]
    error: str | None = None
    new_messages: list[dict[str, Any]] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.error is None


@dataclass(frozen=True)
class ToolCapabilitySnapshot:
    is_read_only: bool
    is_concurrency_safe: bool
    is_enabled: bool


@runtime_checkable
class Tool(Protocol):
    name: ToolName | str
    description: str

    async def execute(self, params: dict[str, Any], context: Any) -> ToolResult:
        ...

    def is_read_only(self) -> bool:
        ...

    def is_concurrency_safe(self) -> bool:
        ...

    def is_enabled(self) -> bool:
        ...


# ── Defaults (fail-closed, mirrors TOOL_DEFAULTS in claude-code) ─────────────

_TOOL_DEFAULTS: dict[str, Any] = {
    "is_read_only": lambda: False,
    "is_concurrency_safe": lambda: False,
    "is_enabled": lambda: True,
}


def build_tool(
    *,
    name: ToolName | str,
    description: str,
    execute: Any,
    is_read_only: Any = None,
    is_concurrency_safe: Any = None,
    is_enabled: Any = None,
) -> Tool:
    class _BuiltTool:
        def __init__(self) -> None:
            self.name = name
            self.description = description
            self._execute = execute
            self._is_read_only = is_read_only or _TOOL_DEFAULTS["is_read_only"]
            self._is_concurrency_safe = is_concurrency_safe or _TOOL_DEFAULTS["is_concurrency_safe"]
            self._is_enabled = is_enabled or _TOOL_DEFAULTS["is_enabled"]

        async def execute(self, params: dict[str, Any], context: Any) -> ToolResult:
            return await self._execute(params, context)

        def is_read_only(self) -> bool:
            return self._is_read_only()

        def is_concurrency_safe(self) -> bool:
            return self._is_concurrency_safe()

        def is_enabled(self) -> bool:
            return self._is_enabled()

    return _BuiltTool()


def get_tool_capability_snapshot(tool: Any) -> ToolCapabilitySnapshot:
    tool_name = getattr(tool, "name", "")
    default_read_only = _tool_name_in_set(tool_name, READONLY_TOOL_NAMES)
    default_concurrency_safe = default_read_only
    return ToolCapabilitySnapshot(
        is_read_only=_read_tool_bool_capability(tool, "is_read_only", default_read_only),
        is_concurrency_safe=_read_tool_bool_capability(tool, "is_concurrency_safe", default_concurrency_safe),
        is_enabled=_read_tool_bool_capability(tool, "is_enabled", True),
    )


def _tool_name_in_set(name: Any, values: frozenset[ToolName]) -> bool:
    normalized = str(name or "").strip()
    if not normalized:
        return False
    try:
        return ToolName(normalized) in values
    except ValueError:
        return False


def _read_tool_bool_capability(tool: Any, capability_name: str, default: bool) -> bool:
    capability = getattr(tool, capability_name, None)
    if not callable(capability):
        return default
    try:
        return bool(capability())
    except Exception:
        # Catalog metadata must never widen privileges or break listing.
        return default
