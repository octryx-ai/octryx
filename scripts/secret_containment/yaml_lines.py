"""Read the shape of a YAML mapping line for the secret containment scanners.

Both scanners ask the same questions of a line, each answered them with its own regex,
and each regex missed a valid YAML form. Every miss was a *silent pass*: the line was not
recognised as a mapping entry at all, so nothing ever classified the value on it.

* A key may be quoted. ``"openRouterApiKey": <material>`` under ``secrets`` is the same
  deployment key as the bare spelling, but a bare-word key pattern does not match that
  line, so the scanner skipped it whole.
* A value may be a flow mapping. ``data: {JWT_SECRET: <material>}`` is a complete Secret
  data block on one line, and a scanner that only descends into block mappings never
  reaches its entries.
* A key may be separated from its colon by spaces (``kind : Secret``), which changes
  nothing about what the line declares.
* A flow mapping may be followed by a trailing comment. ``data: {JWT_SECRET: <material>}
  # bootstrap`` is the same data block as the uncommented spelling, but a reader that
  requires the closing brace at end-of-line does not see a flow mapping at all — and a
  caller that reads "not a flow mapping" as "no entries" then passes the line in silence.
  The comment is cut only where YAML puts one: a ``#`` outside quotes, outside the braces,
  and preceded by whitespace, so a ``#`` inside a quoted value stays part of the value.
* A *whole document* may be one flow mapping. ``{apiVersion: v1, kind: Secret, data:
  {JWT_SECRET: <material>}}`` is a valid Kubernetes Secret on a single line, and a reader
  that only matches ``key: value`` lines sees none of its keys — so the manifest is not
  detected and its data block is never classified. ``root_flow_document`` reads that line,
  keeping the *enclosing* keys instead of flattening to leaves, because ``kind`` is what
  identifies the document and ``data`` is what identifies its secret block. When the braces
  do not balance on the line, the document is reported as incomplete rather than guessed at.
* Kubernetes ``kind: List`` stores objects in a block sequence. ``sequence_item`` exposes the
  ``-`` marker and its content without guessing at the object; ``env_scan`` then applies the
  same mapping and flow-document readers to the sequence item's root.

Line shape only. Nothing here classifies, prints, measures, or decodes a value; that
stays in ``contract``.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass

_QUOTED_KEY = r"\"[^\"]*\"|'[^']*'"
_BARE_KEY = r"[A-Za-z0-9_.\-/]+"
_KEY_LINE = re.compile(
    rf"^(?P<indent>[ \t]*)(?P<key>{_QUOTED_KEY}|{_BARE_KEY})[ \t]*:(?P<rest>.*)$"
)

# ``{{ ... }}`` is a Go template expression, not a YAML flow mapping. Charts write whole
# blocks that way (``data: {{ toYaml .Values.secrets | nindent 2 }}``), so it must not be
# torn into entries; ``contract`` classifies it as a reference.
_TEMPLATE_EXPRESSION = re.compile(r"^\{\{.*\}\}$", re.DOTALL)

_QUOTES = "\"'"
_OPENERS = "[{"
_CLOSERS = "]}"


@dataclass(frozen=True)
class KeyLine:
    """A ``key: rest`` mapping line, with the key unquoted."""

    indent: str
    key: str
    rest: str


@dataclass(frozen=True)
class FlowEntry:
    """One ``key: value`` pair read out of a flow mapping, both still unclassified."""

    key: str
    value: str


@dataclass(frozen=True)
class RootFlowDocument:
    """A YAML document written as a single root-level flow mapping.

    ``entries`` are the *top-level* pairs, deliberately not flattened to leaves: the
    enclosing key is the whole point at document level, since ``kind`` says what the
    document is and ``data`` says which of its values are secret material.

    ``complete`` is False when the flow collections opened on the line do not all close
    again on it. ``entries`` then holds only what could be read up to the unbalanced
    brace — enough for a caller to recognise *what* the document is, never enough to
    claim it was read. A multi-line flow mapping, and a JSON-style manifest spread over
    several lines, both land here; a caller that treats incomplete as "nothing to see"
    reintroduces the silent pass this type exists to prevent.
    """

    entries: tuple[FlowEntry, ...]
    complete: bool


@dataclass(frozen=True)
class SequenceItem:
    """One block-sequence item before its content is interpreted.

    ``indent`` is the whitespace before the ``-`` marker. ``content`` is the
    remainder after the marker and its separating whitespace. An empty content
    string is valid: the item's mapping may start on the following line.
    """

    indent: str
    content: str


def unquote(token: str) -> str:
    """Strip one matching pair of surrounding quotes from a key or scalar token."""
    token = token.strip()
    if len(token) > 1 and token[0] == token[-1] and token[0] in _QUOTES:
        return token[1:-1]
    return token


def match_key_line(raw: str) -> KeyLine | None:
    """The mapping entry a line declares, or None when the line is not one."""
    match = _KEY_LINE.match(raw)
    if match is None:
        return None
    return KeyLine(
        match.group("indent"), unquote(match.group("key")), match.group("rest")
    )


def sequence_item(raw: str) -> SequenceItem | None:
    """Return a YAML block-sequence item, or ``None`` for an ordinary line.

    YAML requires separation after the ``-`` indicator, so ``---`` and negative
    scalars are not sequence items. The caller owns document structure; this
    helper only exposes the marker and never classifies its content.
    """

    stripped = raw.lstrip(" \t")
    if not stripped.startswith("-"):
        return None
    if len(stripped) > 1 and stripped[1] not in " \t":
        return None
    indent = raw[: len(raw) - len(stripped)]
    return SequenceItem(indent, stripped[1:].lstrip(" \t"))


def strip_trailing_comment(value: str) -> str:
    """The value with its trailing YAML comment removed, if it has one.

    A ``#`` only starts a comment where YAML says it does: outside quotes, outside a flow
    collection, and at the start of the value or after whitespace. ``{K: "a # b"} # note``
    therefore loses ``# note`` and keeps ``# b``. An unterminated flow mapping keeps its
    ``#`` too, because that ``#`` is inside the braces — which leaves the value unreadable,
    and unreadable is the caller's fail-closed case, not a silent pass.
    """
    for index in _top_level_positions(value, "#"):
        if index == 0 or value[index - 1] in " \t":
            return value[:index].rstrip()
    return value


def is_template_expression(value: str) -> bool:
    """True when the value is a Go template expression (``{{ ... }}``) rather than YAML data."""
    return bool(_TEMPLATE_EXPRESSION.match(strip_trailing_comment(value.strip())))


def flow_mapping_entries(value: str) -> list[FlowEntry] | None:
    """The entries of a flow mapping (``{A: x, B: y}``), or None when the value is not one.

    A nested flow mapping contributes its own leaf entries, so nothing inside the braces
    stays unclassified. A flow sequence, and an entry without a key, stay one entry and are
    handed to the caller as the text they are, which fails closed: an unrecognised shape is
    classified as material rather than dropped.

    None means "not a readable flow mapping" and covers two different situations — a plain
    scalar and a malformed ``{...`` alike. Callers that recognise the key as a secret block
    must not read it as "no entries"; see ``env_scan._scan_secret_block_line``.
    """
    stripped = strip_trailing_comment(value.strip())
    if not (stripped.startswith("{") and stripped.endswith("}")):
        return None
    if _TEMPLATE_EXPRESSION.match(stripped):
        return None
    return _flow_entries(stripped[1:-1])


def root_flow_document(raw: str) -> RootFlowDocument | None:
    """The document a root-level flow mapping line declares, or None when it is not one.

    Three conditions make a line a document root rather than a value: it starts at column 0,
    its first character opens a flow mapping, and that ``{`` is not the start of a ``{{ ... }}``
    template expression. Nothing here classifies, prints, or measures a value.
    """
    if raw[:1] in (" ", "\t"):
        return None
    stripped = strip_trailing_comment(raw.strip())
    if not stripped.startswith("{") or stripped.startswith("{{"):
        return None
    if stripped.endswith("}") and _is_balanced(stripped):
        return RootFlowDocument(_top_level_pairs(stripped[1:-1]), True)
    return RootFlowDocument(_top_level_pairs(stripped[1:]), False)


def _flow_entries(body: str) -> list[FlowEntry]:
    """The leaf entries of a flow mapping body: a nested mapping contributes its own leaves."""
    entries: list[FlowEntry] = []
    for key, value in _top_level_items(body):
        if key is None:
            entries.append(FlowEntry("", value))
            continue
        nested = flow_mapping_entries(value)
        if nested is None:
            entries.append(FlowEntry(key, value))
        else:
            entries.extend(nested)
    return entries


def _top_level_pairs(body: str) -> tuple[FlowEntry, ...]:
    """The entries of a flow mapping body without descending into nested mappings."""
    return tuple(
        FlowEntry("" if key is None else key, value)
        for key, value in _top_level_items(body)
    )


def _top_level_items(body: str) -> list[tuple[str | None, str]]:
    """The ``key, value`` items of a flow mapping body. A None key marks an item without one."""
    items: list[tuple[str | None, str]] = []
    for item in _split_top_level(body, ","):
        split = _split_at_first(item, ":")
        if split is None:
            items.append((None, item))
            continue
        key, tail = split
        items.append((unquote(key), tail.strip()))
    return items


def _is_balanced(text: str) -> bool:
    """True when every quote and flow collection opened in ``text`` is closed again in it."""
    depth = 0
    quote = ""
    for char in text:
        if quote:
            if char == quote:
                quote = ""
        elif char in _QUOTES:
            quote = char
        elif char in _OPENERS:
            depth += 1
        elif char in _CLOSERS:
            depth -= 1
            if depth < 0:
                return False
    return depth == 0 and not quote


def _top_level_positions(text: str, separators: str) -> Iterator[int]:
    """Indexes of ``separators`` outside quotes and outside nested flow collections."""
    depth = 0
    quote = ""
    for index, char in enumerate(text):
        if quote:
            if char == quote:
                quote = ""
        elif char in _QUOTES:
            quote = char
        elif char in _OPENERS:
            depth += 1
        elif char in _CLOSERS:
            depth -= 1
        elif depth == 0 and char in separators:
            yield index


def _split_top_level(body: str, separator: str) -> list[str]:
    parts: list[str] = []
    start = 0
    for index in _top_level_positions(body, separator):
        parts.append(body[start:index])
        start = index + 1
    parts.append(body[start:])
    return [stripped for stripped in (part.strip() for part in parts) if stripped]


def _split_at_first(item: str, separator: str) -> tuple[str, str] | None:
    for index in _top_level_positions(item, separator):
        return item[:index], item[index + 1 :]
    return None
