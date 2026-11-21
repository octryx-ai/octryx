"""Configuration files parsed per format, with the 1-based line of every key.

Which line prefixes make a comment comes from the profile per format
(``configuration.comment_prefixes``); a commented-out ``;key=value`` is a comment, never a key.

- **INI**: ``[Section]`` headers, ``key = value`` pairs split at the first ``=``, and a line
  starting with a profile comment prefix (``#``, ``;``, ``\\``) is a comment. A line starting with a
  profile continuation prefix (``configuration.continuation_prefixes``, e.g. ``+``) continues the
  previous value (the prefix reads as a space; indentation is ignored); a value ending in such a
  prefix (a regular expression) is never a continuation. A continuation line that reads as
  ``key=value`` with a secret key or value is never joined: it is its own, redacted setting. The
  profile allows only 1-3 punctuation characters as a comment or continuation prefix, so a prefix
  never swallows a key. The comment lines directly above a key
  belong to it (they carry ticket keys such as ``; PROJ-123: reduced from 5000ms to 500ms.``).
- **Properties**: ``key=value``, ``key: value`` or ``key value``; profile comments (``#``, ``!``,
  ``;``); a trailing backslash continues the value.
- **YAML** (Helm values): every scalar leaf under its dotted path (``app.image.tag``), list items
  as ``[index]``; the line is the leaf's own.

Values the shared redaction policy treats as secrets (``redaction_policy.is_secret_setting``: by the
key's last word, camel/snake/kebab-case aware, or by value, including ``user:password@`` and JDBC
``user/password@`` connection strings) are replaced by ``[redacted]`` and flagged, so they are never
stored, compared or shown. The registry sections (profile ``registry_sections``) type the other
sections: ``[Services] HttpService_Ping = HttpService(HttpServer, /ping, Ping)`` makes
``[HttpService_Ping]`` an ``HttpService``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import yaml

from ...redaction_policy import REDACTED_SECRET, is_secret_setting

MAX_ENTRIES_PER_FILE = 5000
MAX_VALUE_CHARS = 300
MAX_YAML_DEPTH = 12
_SECTION = re.compile(r"^\[([^\]]{1,200})\]\s*$")
_REGISTRY_TYPE = re.compile(r"^\s*([A-Za-z_][\w$]*)")


@dataclass(slots=True)
class ConfigEntry:
    section: str
    key: str
    value: str
    line: int
    redacted: bool = False
    comments: list[tuple[int, str]] = field(default_factory=list)


@dataclass(slots=True)
class ParsedConfig:
    entries: list[ConfigEntry] = field(default_factory=list)
    # Section -> its line (INI only).
    sections: dict[str, int] = field(default_factory=dict)
    # Comment lines with their numbers (ticket mentions at file level).
    comments: list[tuple[int, str]] = field(default_factory=list)
    skipped_lines: int = 0
    truncated: bool = False

    def section_types(self, registry_sections: tuple[str, ...]) -> dict[str, str]:
        """Section name -> plugin type from the registry sections; a section not listed types itself."""
        types: dict[str, str] = {}
        for entry in self.entries:
            if entry.section in registry_sections and not entry.redacted:
                found = _REGISTRY_TYPE.match(entry.value)
                if found:
                    types.setdefault(entry.key, found.group(1))
        return types


def is_secret(key: str, value: str) -> bool:
    return is_secret_setting(key, value) or REDACTED_SECRET in value


def _entry(section: str, key: str, value: str, line: int, comments) -> ConfigEntry:
    value = " ".join(value.split())[:MAX_VALUE_CHARS]
    if is_secret(key, value):
        return ConfigEntry(section, key, REDACTED_SECRET, line, True, comments)
    return ConfigEntry(section, key, value, line, False, comments)


def _add(parsed: ParsedConfig, entry: ConfigEntry) -> None:
    if len(parsed.entries) >= MAX_ENTRIES_PER_FILE:
        parsed.truncated = True
        return
    parsed.entries.append(entry)


def _continue(entry: ConfigEntry, text: str) -> None:
    """Append a ``+`` continuation line; the joined value is checked for secrets again."""
    if entry.redacted:
        return
    joined = " ".join(f"{entry.value} {text}".split())[:MAX_VALUE_CHARS]
    if is_secret(entry.key, joined):
        entry.value, entry.redacted = REDACTED_SECRET, True
    else:
        entry.value = joined


def _secret_setting(*texts: str) -> str | None:
    """The key of the first text that reads as ``key=value`` with a secret key or value, else ``None``."""
    for text in texts:
        key, sign, value = text.partition("=")
        key = key.strip()
        if sign and key and is_secret(key, value.strip()):
            return key
    return None


def parse_ini(
    text: str, comment_prefixes: tuple[str, ...], continuation_prefixes: tuple[str, ...]
) -> ParsedConfig:
    parsed = ParsedConfig()
    section = ""
    pending: list[tuple[int, str]] = []
    last: ConfigEntry | None = None
    for number, raw in enumerate(text.splitlines(), start=1):
        stripped = raw.strip()
        if not stripped:
            pending = []
            continue
        if stripped.startswith(comment_prefixes):
            comment = (number, stripped[:MAX_VALUE_CHARS])
            pending.append(comment)
            parsed.comments.append(comment)
            continue
        prefix = next((item for item in continuation_prefixes if stripped.startswith(item)), None)
        own = _secret_setting(stripped[len(prefix):], stripped) if prefix is not None else None
        if own is not None:
            # A continuation line that reads as ``secret_key=value`` is never joined: it is its own,
            # redacted setting, so no prefix folds a secret into a value redaction does not catch.
            _add(parsed, _entry(section, own, REDACTED_SECRET, number, pending))
            pending, last = [], None
            continue
        if prefix is not None:
            # A continuation line extends the previous value (the prefix reads as a space).
            if last is not None:
                _continue(last, stripped[len(prefix):].strip())
            else:
                parsed.skipped_lines += 1
            continue
        header = _SECTION.match(stripped)
        if header:
            section = header.group(1).strip()
            parsed.sections.setdefault(section, number)
            pending, last = [], None
            continue
        if "=" not in stripped:
            parsed.skipped_lines += 1
            pending, last = [], None
            continue
        key, value = (part.strip() for part in stripped.split("=", 1))
        last = None
        if key:
            before = len(parsed.entries)
            _add(parsed, _entry(section, key, value, number, pending))
            last = parsed.entries[-1] if len(parsed.entries) > before else None
        pending = []
    return parsed


def parse_properties(text: str, comment_prefixes: tuple[str, ...] = ("#", "!")) -> ParsedConfig:
    parsed = ParsedConfig()
    lines = text.splitlines()
    pending: list[tuple[int, str]] = []
    index = 0
    while index < len(lines):
        number, stripped = index + 1, lines[index].strip()
        index += 1
        if not stripped:
            pending = []
            continue
        if stripped.startswith(comment_prefixes):
            comment = (number, stripped[:MAX_VALUE_CHARS])
            pending.append(comment)
            parsed.comments.append(comment)
            continue
        while stripped.endswith("\\") and index < len(lines):
            stripped = stripped[:-1] + lines[index].strip()
            index += 1
        match = re.match(r"^([^=:\s]+)\s*[=:\s]\s*(.*)$", stripped)
        if match is None:
            parsed.skipped_lines += 1
            continue
        _add(parsed, _entry("", match.group(1), match.group(2), number, pending))
        pending = []
    return parsed


def parse_yaml(text: str, comment_prefixes: tuple[str, ...] = ("#",)) -> ParsedConfig:
    parsed = ParsedConfig()
    try:
        documents = list(yaml.compose_all(text, Loader=yaml.SafeLoader))
    except yaml.YAMLError:
        parsed.skipped_lines = len(text.splitlines())
        return parsed
    for line, comment in ((n + 1, raw.strip()) for n, raw in enumerate(text.splitlines())):
        if comment.startswith(comment_prefixes):
            parsed.comments.append((line, comment[:MAX_VALUE_CHARS]))

    def walk(node, path: str, depth: int) -> None:
        if node is None or depth > MAX_YAML_DEPTH:
            return
        if isinstance(node, yaml.MappingNode):
            for key_node, value_node in node.value:
                name = str(getattr(key_node, "value", ""))
                walk(value_node, f"{path}.{name}" if path else name, depth + 1)
        elif isinstance(node, yaml.SequenceNode):
            for position, item in enumerate(node.value):
                walk(item, f"{path}[{position}]", depth + 1)
        elif isinstance(node, yaml.ScalarNode):
            leaf = re.split(r"[.\[]", path)[-1] if path else ""
            _add(parsed, _entry("", path, str(node.value), node.start_mark.line + 1, []))
            if leaf and parsed.entries and is_secret(leaf, str(node.value)):
                parsed.entries[-1].value, parsed.entries[-1].redacted = REDACTED_SECRET, True

    for document in documents:
        walk(document, "", 0)
    return parsed


def parse_config(
    text: str, file_format: str, comment_prefixes: tuple[str, ...], continuation_prefixes: tuple[str, ...]
) -> ParsedConfig:
    if file_format == "ini":
        return parse_ini(text, comment_prefixes, continuation_prefixes)
    if file_format == "properties":
        return parse_properties(text, comment_prefixes)
    return parse_yaml(text, comment_prefixes)


__all__ = ["ConfigEntry", "ParsedConfig", "is_secret", "parse_config", "parse_ini", "parse_properties", "parse_yaml"]
