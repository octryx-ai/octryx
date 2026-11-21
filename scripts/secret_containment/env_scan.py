"""Scan env-style templates and Kubernetes Secret manifests for secret material.

Two shapes are covered:

``env files``
    ``KEY=value`` templates such as ``base/secret-template.env``.
    Only keys that are secret-bearing by name are checked, because env files also
    legitimately carry plain configuration.

``Kubernetes Secret manifests``
    Any document with ``kind: Secret``, detected by content rather than by file
    name (``overlays/eks/secrets.env`` is such a manifest despite
    its ``.env`` name). Inside ``data`` / ``stringData`` *every* entry is secret
    material by definition, so every entry must satisfy the placeholder contract.
    Both the detection and the data block read the lines through ``yaml_lines``, so a
    trailing comment on ``kind: Secret`` and a one-line ``data: {KEY: value}`` mapping
    are the manifest they are instead of shapes the scanner walks past. A ``data`` /
    ``stringData`` line whose value is non-empty but unreadable is reported rather than
    skipped: an unreadable secret block is exactly where material would hide.

    A document may also be one root-level flow mapping — ``{apiVersion: v1, kind: Secret,
    data: {JWT_SECRET: <material>}}`` — which declares no ``key: value`` line at all. That
    line is read as a document: when its braces close on it, its ``data`` / ``stringData``
    entries are classified exactly as a block line's are; when they do not, the document is
    reported as unreadable, because the rest of it is past what a line reader can see.

    Kubernetes ``kind: List`` is a container, not an exemption. Block-sequence items are
    followed at their own mapping indentation, including the common ``- apiVersion`` then
    ``kind: Secret`` spelling. A List shape this bounded reader cannot interpret is refused as
    an unreadable document. Inside a Secret data block, scalar continuations and explicit or
    merge mapping syntax that cannot be classified are refused as an unreadable block instead
    of being skipped.

An empty value is accepted here: an empty entry ships no material and, unlike a
Helm values key, has no chart default substituted for it.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

from .contract import (
    BLOCK_SCALAR_INDICATORS,
    EMPTY,
    MATERIAL,
    REASON_BLOCK_SCALAR,
    REASON_BLOCK_UNREADABLE,
    REASON_DOCUMENT_UNREADABLE,
    REASON_NOT_PLACEHOLDER,
    REASON_WEAK_VALUE,
    WEAK,
    Finding,
    classify_value,
    is_secret_env_key,
    strip_scalar,
)
from .yaml_lines import (
    FlowEntry,
    KeyLine,
    RootFlowDocument,
    flow_mapping_entries,
    is_template_expression,
    match_key_line,
    root_flow_document,
    sequence_item,
    strip_trailing_comment,
)

# Env-style template names (deployment scope is applied by the caller). Documentation
# copies (``app.env.example``) are matched through ``file_kinds.is_env_file``, which
# strips the copy suffix before comparing, so they need no pattern of their own.
ENV_FILE_PATTERNS = ("*.env", ".env.*")

_ENV_LINE = re.compile(r"^(?:export\s+)?(?P<key>[A-Za-z_][A-Za-z0-9_]*)=(?P<rest>.*)$")
_EXPLICIT_KIND_KEY = re.compile(r"^\?\s+(?:kind|'kind'|\"kind\")\s*(?:#.*)?$")
_MERGE_KEY = re.compile(r"^<<\s*:")

SECRET_DATA_BLOCKS = ("data", "stringdata")

SECRET_KIND = "Secret"
LIST_KIND = "List"
UNKNOWN_KIND = "__unreadable_kind__"


def looks_like_secret_manifest(text: str) -> bool:
    """True when the text declares a Kubernetes Secret, whatever the file is called.

    A trailing comment does not change what ``kind: Secret`` declares, so the line is read
    as a mapping entry rather than matched to the end of the line. A document written as one
    root-level flow mapping declares its kind inside the braces, so that form is read too —
    including when the braces do not close on the line, where the entries read so far are
    still enough to tell that the document is a Secret.
    """
    for document in _split_documents(text):
        root_kind = _root_document_kind(document.text)
        # A List is a manifest container. It must reach the scanner even when a
        # sequence item's ``kind`` uses a shape this bounded reader cannot parse;
        # the unreadable item then fails closed instead of bypassing the preflight.
        if root_kind in (SECRET_KIND, LIST_KIND, UNKNOWN_KIND):
            return True
        incomplete_root_flow = False
        sequence_indent: int | None = None
        for raw in document.text.splitlines():
            root_flow = root_flow_document(raw)
            if root_flow is not None and not root_flow.complete:
                incomplete_root_flow = True
            item = sequence_item(raw)
            if item is not None:
                sequence_indent = _indent_width(item.indent) + 2
                line = match_key_line(item.content)
                if (
                    line is not None
                    and not line.indent
                    and _line_declares_kind(line, SECRET_KIND)
                ):
                    return True
                flow = root_flow_document(item.content)
                if flow is not None and _declares_kind_in(flow.entries, SECRET_KIND):
                    return True
                continue
            line = match_key_line(raw)
            if line is None:
                continue
            indent = _indent_width(line.indent)
            if sequence_indent is not None and indent < sequence_indent:
                sequence_indent = None
            if (
                sequence_indent == indent or incomplete_root_flow
            ) and _line_declares_kind(line, SECRET_KIND):
                return True
    return False


def _root_document_kind(text: str) -> str:
    """Return the root mapping's declared kind, without inspecting nested mappings."""

    for raw in text.splitlines():
        line = match_key_line(raw)
        if line is not None and not line.indent and line.key == "kind":
            return _kind_value(line.rest)
        if not raw[:1].isspace() and _is_indirect_kind_line(raw):
            # Explicit mapping keys and merged root mappings can provide ``kind``
            # indirectly. This bounded reader cannot resolve them, so route the
            # document into the scanner and refuse it instead of silently passing.
            return UNKNOWN_KIND
        document = root_flow_document(raw)
        if document is not None:
            return _kind_in(document.entries)
    return ""


def _declares_kind_in(entries: Iterable[FlowEntry], kind: str) -> bool:
    return _kind_in(entries) == kind


def _line_declares_kind(line: KeyLine, kind: str) -> bool:
    return line.key == "kind" and _kind_value(line.rest) == kind


def _kind_in(entries: Iterable[FlowEntry]) -> str:
    """Return a direct kind, or UNKNOWN_KIND when YAML can provide it indirectly."""

    for entry in entries:
        if entry.key == "kind":
            return _kind_value(entry.value)
        if entry.key in ("<<", "? kind"):
            return UNKNOWN_KIND
    return ""


def _kind_value(rest: str) -> str:
    """Read a bounded YAML kind scalar without resolving aliases or custom tags.

    A standard string tag and an anchor still leave the scalar on the same line and
    are safe to unwrap. Aliases, custom tags and block scalars require YAML graph or
    constructor semantics, so they return UNKNOWN_KIND and fail closed.
    """

    value = strip_trailing_comment(rest.strip())
    while value:
        token, separator, tail = value.partition(" ")
        if token.startswith("&"):
            if not separator:
                return UNKNOWN_KIND
            value = tail.lstrip()
            continue
        if token in ("!!str", "!<tag:yaml.org,2002:str>"):
            if not separator:
                return UNKNOWN_KIND
            value = tail.lstrip()
            continue
        if token.startswith(("!", "*")) or token in BLOCK_SCALAR_INDICATORS:
            return UNKNOWN_KIND
        break
    return strip_scalar(value)


def _is_indirect_kind_line(raw: str) -> bool:
    """True when a root mapping can obtain ``kind`` through unsupported YAML syntax."""

    stripped = raw.strip()
    return bool(_EXPLICIT_KIND_KEY.fullmatch(stripped) or _MERGE_KEY.match(stripped))


def _indent_width(indent: str) -> int:
    return len(indent.expandtabs(8))


def _report(path: str, number: int, key: str, value: str) -> Finding | None:
    if value in BLOCK_SCALAR_INDICATORS:
        return Finding(path, number, key, REASON_BLOCK_SCALAR)
    classification = classify_value(value)
    if classification == WEAK:
        return Finding(path, number, key, REASON_WEAK_VALUE)
    if classification == MATERIAL:
        return Finding(path, number, key, REASON_NOT_PLACEHOLDER)
    return None


def scan_env_file(path: str, text: str) -> list[Finding]:
    """Report secret-bearing env keys that hold anything but a placeholder."""
    findings: list[Finding] = []
    for number, raw in enumerate(text.splitlines(), start=1):
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        match = _ENV_LINE.match(stripped)
        if match is None or not is_secret_env_key(match.group("key")):
            continue
        value = strip_scalar(match.group("rest"))
        if classify_value(value) == EMPTY:
            continue
        finding = _report(path, number, match.group("key"), value)
        if finding is not None:
            findings.append(finding)
    return findings


def scan_secret_manifest(path: str, text: str) -> list[Finding]:
    """Report ``data`` / ``stringData`` entries of Secret documents that carry material."""
    findings: list[Finding] = []
    for document in _split_documents(text):
        if not looks_like_secret_manifest(document.text):
            continue
        findings.extend(_scan_secret_document(path, document))
    return findings


class _Document:
    __slots__ = ("text", "offset")

    def __init__(self, text: str, offset: int) -> None:
        self.text = text
        self.offset = offset


def _split_documents(text: str) -> list[_Document]:
    documents: list[_Document] = []
    lines = text.splitlines()
    start = 0
    for index, line in enumerate(lines):
        if line.rstrip() == "---" and index > start:
            documents.append(_Document("\n".join(lines[start:index]), start))
            start = index + 1
    documents.append(_Document("\n".join(lines[start:]), start))
    return documents


def _scan_secret_document(path: str, document: _Document) -> list[Finding]:
    findings: list[Finding] = []
    root_kind = _root_document_kind(document.text)
    if root_kind == UNKNOWN_KIND:
        findings.append(Finding(path, document.offset + 1, "kind", REASON_DOCUMENT_UNREADABLE))
    list_document = root_kind == LIST_KIND
    sequence_indent: int | None = None
    secret_indent: int | None = None
    data_indent: int | None = None
    data_key = ""
    last_entry_key = ""
    unreadable_region = False
    for index, raw in enumerate(document.text.splitlines()):
        number = document.offset + index + 1
        stripped = raw.strip()
        if not stripped or stripped.startswith("#") or stripped.startswith("{{"):
            continue
        raw_indent = _indent_width(raw[: len(raw) - len(raw.lstrip(" \t"))])
        item = sequence_item(raw)
        if data_indent is not None and raw_indent > data_indent and item is not None:
            if not unreadable_region:
                findings.append(
                    Finding(
                        path,
                        number,
                        last_entry_key or data_key,
                        REASON_BLOCK_UNREADABLE,
                    )
                )
            unreadable_region = True
            continue

        line = match_key_line(raw)
        if item is not None:
            effective_indent = _indent_width(item.indent) + 2
            sequence_indent = effective_indent
            # A sibling item closes the previous object. A sequence nested in a
            # Secret's metadata does not: clearing the outer state there would let
            # a later root-level ``data`` block pass unread.
            if secret_indent is None or effective_indent <= secret_indent:
                secret_indent = None
                data_indent = None
                data_key = ""
                last_entry_key = ""
                unreadable_region = False
            line = match_key_line(item.content)
            if line is not None and not line.indent:
                line = KeyLine(" " * effective_indent, line.key, line.rest)
            else:
                flow = root_flow_document(item.content)
                if flow is not None:
                    findings.extend(_scan_root_flow_document(path, number, flow))
                elif item.content and list_document:
                    findings.append(
                        Finding(path, number, "", REASON_DOCUMENT_UNREADABLE)
                    )
                continue
        if line is None:
            if data_indent is not None and raw_indent > data_indent:
                if not unreadable_region:
                    findings.append(
                        Finding(
                            path,
                            number,
                            last_entry_key or data_key,
                            REASON_BLOCK_UNREADABLE,
                        )
                    )
                unreadable_region = True
                continue
            root_flow = root_flow_document(raw)
            if root_flow is None:
                continue
            # Deliberately leaves the block state alone: a root flow mapping is not a
            # block-level key, and a document cannot validly hold both forms, so on malformed
            # input the enclosing block keeps applying rather than being silently closed.
            findings.extend(_scan_root_flow_document(path, number, root_flow))
            continue

        indent = _indent_width(line.indent)
        if sequence_indent is not None and indent < sequence_indent:
            sequence_indent = None
        if data_indent is not None and indent > data_indent:
            entries = _entries_of(line.key, line.rest)
            entry_findings = _scan_entries(path, number, entries)
            findings.extend(entry_findings)
            unreadable_region = bool(entry_findings)
            last_entry_key = line.key
            continue

        data_indent = None
        data_key = ""
        last_entry_key = ""
        unreadable_region = False
        candidate_mapping = indent == 0 or indent == sequence_indent
        if candidate_mapping and line.key == "kind":
            kind = _kind_value(line.rest)
            if kind == SECRET_KIND:
                secret_indent = indent
            elif kind == UNKNOWN_KIND:
                findings.append(
                    Finding(path, number, "kind", REASON_DOCUMENT_UNREADABLE)
                )
                secret_indent = None
            elif secret_indent is not None and indent <= secret_indent:
                secret_indent = None
            continue
        if candidate_mapping and line.key == "<<":
            findings.append(Finding(path, number, "kind", REASON_DOCUMENT_UNREADABLE))
            secret_indent = None
            continue
        if list_document and indent == 0 and line.key == "items":
            value = strip_trailing_comment(line.rest.strip())
            if value not in ("", "[]"):
                findings.append(
                    Finding(path, number, "items", REASON_DOCUMENT_UNREADABLE)
                )
            continue
        if secret_indent is None or indent != secret_indent:
            continue
        if line.key.lower() not in SECRET_DATA_BLOCKS:
            continue
        data_indent = indent
        data_key = line.key
        block_findings = _scan_secret_block_value(path, number, line.key, line.rest)
        findings.extend(block_findings)
        unreadable_region = bool(block_findings)
    return findings


def _scan_root_flow_document(
    path: str, number: int, document: RootFlowDocument
) -> list[Finding]:
    """Classify the secret blocks of a document written as one root-level flow mapping.

    The enclosing line is a root flow document. A Secret has two answers and neither is
    silence; a flow-style List is refused because its nested sequence is outside this reader:

    * the braces close on this line — every top-level ``data`` / ``stringData`` entry is
      classified exactly as a block line is, so ``{kind: Secret, data: {JWT_SECRET: <material>}}``
      reports that entry instead of nothing;
    * they do not close — the document continues past what a line reader can see (a multi-line
      flow mapping, a JSON-style manifest, a truncated line), so it is reported as unreadable.
      That is the fail-closed half: a Secret document this reader cannot take apart is exactly
      where material would hide. The finding names the file and the line; no key is claimed,
      because which keys the document holds is precisely what could not be read.
    """
    if not document.complete:
        return [Finding(path, number, "", REASON_DOCUMENT_UNREADABLE)]
    kind = _kind_in(document.entries)
    if kind == UNKNOWN_KIND:
        return [Finding(path, number, "kind", REASON_DOCUMENT_UNREADABLE)]
    if kind == LIST_KIND:
        # A flow-style List carries a sequence inside ``items``. This bounded
        # reader does not guess across that second grammar; refusing the document
        # is the safe result and still keeps every value out of the finding.
        return [Finding(path, number, "", REASON_DOCUMENT_UNREADABLE)]
    if kind != SECRET_KIND:
        return []
    findings: list[Finding] = []
    for entry in document.entries:
        if entry.key.lower() in SECRET_DATA_BLOCKS:
            findings.extend(
                _scan_secret_block_value(path, number, entry.key, entry.value)
            )
    return findings


def _scan_secret_block_value(
    path: str, number: int, key: str, rest: str
) -> list[Finding]:
    """Classify whatever a ``data`` / ``stringData`` block carries on its own line.

    One reader for both spellings of the block — an indented block line and a top-level entry
    of a root flow document — so the two cannot drift apart. Four shapes, and the last one is
    why this is a function rather than a call to ``flow_mapping_entries``:

    * empty — the block key names the block and the entries follow as indented lines, which
      the caller reads next;
    * a flow mapping (``data: {A: x}``, trailing comment allowed) — a whole data block on one
      line, classified entry by entry;
    * a template expression (``data: {{ toYaml .Values.secrets | nindent 2 }}``) — the
      material is resolved by the renderer and is not in this file;
    * anything else — non-empty and unreadable (a malformed ``data: {A: x``, a bare scalar).
      Reading that as "no entries" is the fail-open form this function exists to close, so it
      is reported. The finding names the block key and the reason code; the value that could
      not be read is never part of it.
    """
    entries = flow_mapping_entries(rest)
    if entries is not None:
        return _scan_entries(
            path, number, [(entry.key, entry.value) for entry in entries]
        )
    value = strip_trailing_comment(rest.strip())
    if value == "" or is_template_expression(value):
        return []
    return [Finding(path, number, key, REASON_BLOCK_UNREADABLE)]


def _entries_of(key: str, rest: str) -> list[tuple[str, str]]:
    """The (key, value) pairs one data entry contributes, flow mapping included."""
    entries = flow_mapping_entries(rest)
    if entries is None:
        return [(key, rest)]
    return [(entry.key, entry.value) for entry in entries]


def _scan_entries(
    path: str, number: int, entries: Iterable[tuple[str, str]]
) -> list[Finding]:
    """Classify every entry found on one line. Every ``data`` entry is material by contract."""
    findings: list[Finding] = []
    for key, raw_value in entries:
        value = strip_scalar(raw_value)
        if classify_value(value) == EMPTY:
            continue
        finding = _report(path, number, key, value)
        if finding is not None:
            findings.append(finding)
    return findings
