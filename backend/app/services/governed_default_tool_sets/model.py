"""The value types of a governed default tool set."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ToolFamily:
    name: str
    tools: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class GovernedToolSet:
    capability_type: str
    set_id: str
    version: int
    title: str
    description: str
    families: tuple[ToolFamily, ...]

    @property
    def key(self) -> str:
        """The recorded identity of the set, e.g. ``diagnosis.v1``."""
        return f"{self.set_id}.v{self.version}"

    @property
    def tools(self) -> tuple[str, ...]:
        """Every tool of the set, in declared priority order (first family first)."""
        return tuple(dict.fromkeys(tool for family in self.families for tool in family.tools))
