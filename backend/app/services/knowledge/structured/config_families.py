"""Linkage inputs: variant families and placeholder values of configured settings.

- **Families.** A profile variant file (``app.ini-test``) is judged together with its base file
  (``app.ini``): the settings with the same repository, base path, section, key and occurrence
  (the n-th time the key appears in its section) form one family. Its *lead* is the base file's
  setting (or, without one, the first variant's); every finding is stated once, on the lead, and
  lists the variants. A file without a base counterpart leads its own families.
- **Placeholders.** A value holding the profile placeholder (``${Dec_ThreadCount}``) is resolved
  from the placeholder sources of the same repository and component (profile
  ``placeholder_sources``: key=value files such as ``*_config.properties``), recursively up to
  :data:`MAX_DEPTH`. A name no source defines, a redacted definition or a cycle leaves the value
  *unresolved*: it is never compared with a default or with another component's value.
"""

from __future__ import annotations

import fnmatch
import posixpath
from dataclasses import dataclass, field
from typing import Any

from .config_files import is_secret
from .profile_patterns import ProfileMatch, ProfilePattern

MAX_DEPTH = 5


@dataclass(frozen=True, slots=True)
class NodeRow:
    """A structured node as the linkage reads it."""

    node_id: str
    node_type: str
    revision_id: str
    span_ordinal: int | None
    line: int | None
    label: str
    properties: dict[str, Any]

    @property
    def cite(self) -> tuple[str, int, int | None]:
        return (self.revision_id, self.span_ordinal or 1, self.line)


@dataclass(slots=True)
class Family:
    lead: NodeRow
    variants: list[NodeRow] = field(default_factory=list)

    @property
    def members(self) -> list[NodeRow]:
        return [self.lead, *self.variants]


def families(settings: list[NodeRow]) -> list[Family]:
    """The settings grouped by variant family, in the order of each family's first setting."""
    occurrence: dict[tuple, int] = {}
    grouped: dict[tuple, list[tuple[int, NodeRow]]] = {}
    ordered = sorted(enumerate(settings), key=lambda item: (item[1].properties.get("path") or "", item[1].line or 0))
    for position, setting in ordered:
        props = setting.properties
        own = (props.get("repo"), props.get("path"), props.get("section"), props.get("key"))
        index = occurrence.get(own, 0)
        occurrence[own] = index + 1
        base = props.get("base_path") or props.get("path")
        key = (props.get("repo"), base, props.get("section"), props.get("key"), index)
        grouped.setdefault(key, []).append((position, setting))
    result = []
    for members in grouped.values():
        # The base file's setting leads; without one, the first variant file's.
        members.sort(key=lambda item: (item[1].properties.get("variant") is not None,
                                       item[1].properties.get("path") or ""))
        result.append((min(position for position, _ in members), Family(members[0][1], [m for _, m in members[1:]])))
    return [family for _, family in sorted(result, key=lambda item: item[0])]


@dataclass(frozen=True, slots=True)
class Resolved:
    """A setting's value after placeholder substitution; ``value`` is ``None`` when it stays unresolved."""

    raw: str
    value: str | None
    unresolved: tuple[str, ...] = ()
    sources: tuple[NodeRow, ...] = ()

    @property
    def substituted(self) -> bool:
        return bool(self.sources)


class Placeholders:
    """Placeholder definitions per ``(repository, component)`` from the profile's placeholder sources."""

    def __init__(self, settings: list[NodeRow], pattern: ProfilePattern | None, sources: tuple[str, ...]) -> None:
        self.pattern = pattern
        self._defined: dict[tuple[Any, Any], dict[str, NodeRow]] = {}
        definitions: set[str] = set()
        for setting in settings:
            props = setting.properties
            name = posixpath.basename(props.get("path") or "")
            if not any(fnmatch.fnmatchcase(name, glob) for glob in sources):
                continue
            definitions.add(setting.node_id)
            scope = self._defined.setdefault((props.get("repo"), props.get("component")), {})
            scope.setdefault(props.get("key") or "", setting)
        # The settings of placeholder source files: definitions, not configuration of their own.
        self.definitions = frozenset(definitions)

    def resolve(self, setting: NodeRow) -> Resolved:
        props = setting.properties
        raw = str(props.get("value") or "")
        if self.pattern is None or props.get("redacted") or not self.pattern.search(raw):
            return Resolved(raw, raw)
        defined = self._defined.get((props.get("repo"), props.get("component")), {})
        missing: list[str] = []
        used: dict[str, NodeRow] = {}

        def substitute(found: ProfileMatch) -> str:
            name = found.group("name")
            source = defined.get(name)
            if source is None or source.properties.get("redacted") or source.node_id == setting.node_id:
                missing.append(name)
                return found.group(0)
            used.setdefault(source.node_id, source)
            return str(source.properties.get("value") or "")

        value = raw
        for _ in range(MAX_DEPTH):
            value = self.pattern.sub(substitute, value)
            if missing or not self.pattern.search(value):
                break
        if not missing and self.pattern.search(value):
            # Still a placeholder after MAX_DEPTH rounds: a cycle or a chain too deep to trust.
            missing.extend(found.group("name") for found in self.pattern.finditer(value))
        if missing:
            return Resolved(raw, None, tuple(dict.fromkeys(missing)), tuple(used.values()))
        if is_secret(str(props.get("key") or ""), value):
            # Substitution can rebuild a credential no single line held (``mysql://${Creds}@db``):
            # the resolved value is withheld like a redacted one, the raw placeholder stays.
            return Resolved(raw, None, (), tuple(used.values()))
        return Resolved(raw, value, (), tuple(used.values()))


def variant_item(setting: NodeRow, resolved: Resolved | None = None, **extra: Any) -> dict[str, Any]:
    """A variant as an edge property: where it is and what it holds (never a redacted value)."""
    props = setting.properties
    item = {"path": props.get("path"), "variant": props.get("variant"), "line": props.get("line"),
            "value": props.get("value")}
    if resolved is not None and resolved.substituted and resolved.value is not None:
        item["resolved_value"] = resolved.value
    item.update(extra)
    return item


__all__ = ["MAX_DEPTH", "Family", "NodeRow", "Placeholders", "Resolved", "families", "variant_item"]
