"""A Custom REST record as a Knowledge item: its header (id, title, link, version marker) and its content bytes.

**Header.** Read through the source's field mapping (dotted paths, ``rest_config``):

- the external id is the mapped id when it is a ledger-safe key; any other id (spaces, slashes, 200+ characters)
  becomes ``h-<sha256>`` of it, stable across runs, and the original id is kept for the detail call;
- the version marker is ``<version>@<updated_at>`` of what is mapped; one longer than the runner's 80 characters is
  hashed, never cut (two versions sharing a prefix must not look unchanged). A record with neither value cannot be
  versioned and is skipped (``record_unversioned``), like one without an id (``record_without_id``);
- the link is kept only as an openable ``http(s)`` URL (``normalize_source_url``), else the item has none.

**Content** (what the ledger stores and hashes, so it is deterministic):

- ``application/json`` (default): Markdown, the title as heading and then the mapped ``content`` value, or the whole
  record without the mapped ``updated_at``/``version`` (a touch without a change yields identical bytes), as nested
  lists in key order. Capped like ServiceNow records (``servicenow_render.MAX_BODY_CHARS``);
- ``text/markdown``, ``text/plain``, ``text/html``: the mapped field's text as is (HTML through the parser sandbox);
- ``application/pdf``: the mapped field holds the PDF base64-encoded (the executor reads JSON answers only).

Synced text is third-party content: it is stored as data and reaches a model only through the consumers that read
Knowledge, never as an instruction of this connector.
"""

from __future__ import annotations

import base64
import binascii
import copy
import hashlib
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from ....rest_connector.response import get_path
from ...ledger.errors import InvalidEvidenceRequestError
from ..source_url import normalize_source_url
from .contract import REASON_SOURCE_CONTRACT_VIOLATION, ConnectorError
from .rest_config import MEDIA_JSON
from .servicenow_render import MAX_BODY_CHARS
from .source_dates import source_date

MAX_TITLE_CHARS = 300
MAX_ID_CHARS = 200
MAX_MARKER_CHARS = 80
MAX_DEPTH = 6
SKIP_WITHOUT_ID = "record_without_id"
SKIP_UNVERSIONED = "record_unversioned"
_LEDGER_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,119}$")


@dataclass(frozen=True)
class RecordHeader:
    external_id: str
    original_id: str
    title: str
    source_url: str | None
    version_marker: str
    changed_at: datetime | None


def _scalar(value: Any) -> str | None:
    if isinstance(value, bool) or not isinstance(value, str | int | float):
        return None
    text = " ".join(str(value).split())
    return text or None


def _at(record: Mapping[str, Any], mapping: Mapping[str, str], name: str) -> Any:
    path = mapping.get(name)
    return get_path(record, path) if path else None


def external_id_of(original: str) -> str:
    return original if _LEDGER_ID.fullmatch(original) else "h-" + hashlib.sha256(original.encode()).hexdigest()[:40]


def _marker(version: str | None, updated: str | None) -> str:
    marker = "@".join(part for part in (version, updated) if part)
    return marker if len(marker) <= MAX_MARKER_CHARS else "sha256:" + hashlib.sha256(marker.encode()).hexdigest()[:64]


def _link(value: Any) -> str | None:
    try:
        return normalize_source_url(_scalar(value))
    except InvalidEvidenceRequestError:
        return None


def record_header(record: Mapping[str, Any], mapping: Mapping[str, str], fallback_title: str
                  ) -> RecordHeader | str:
    """The record's header, or the fixed reason it is skipped."""
    original = _scalar(_at(record, mapping, "id"))
    if original is None or len(original) > MAX_ID_CHARS:
        return SKIP_WITHOUT_ID
    version, updated = _scalar(_at(record, mapping, "version")), _scalar(_at(record, mapping, "updated_at"))
    if version is None and updated is None:
        return SKIP_UNVERSIONED
    title = (_scalar(_at(record, mapping, "title")) or f"{fallback_title} {original}")[:MAX_TITLE_CHARS]
    return RecordHeader(external_id=external_id_of(original), original_id=original, title=title,
                        source_url=_link(_at(record, mapping, "url")), version_marker=_marker(version, updated),
                        changed_at=source_date(updated))


def _without(record: Mapping[str, Any], paths: list[str]) -> Any:
    """A copy of ``record`` without the volatile mapped paths (top level or nested dotted keys)."""
    copied = copy.deepcopy(dict(record))
    for path in paths:
        node: Any = copied
        *parents, leaf = path.split(".")
        for part in parents:
            node = node.get(part) if isinstance(node, dict) else None
        if isinstance(node, dict):
            node.pop(leaf, None)
    return copied


def _lines(value: Any, depth: int, out: list[str]) -> None:
    indent = "  " * depth
    if depth >= MAX_DEPTH:
        out.append(f"{indent}- …")
        return
    if isinstance(value, Mapping):
        for key in sorted(value, key=str):
            child = value[key]
            if isinstance(child, Mapping | list) and child:
                out.append(f"{indent}- {key}:")
                _lines(child, depth + 1, out)
            elif _scalar(child) is not None:
                out.append(f"{indent}- {key}: {_scalar(child)}")
    elif isinstance(value, list):
        for child in value:
            if isinstance(child, Mapping | list):
                out.append(f"{indent}-")
                _lines(child, depth + 1, out)
            elif _scalar(child) is not None:
                out.append(f"{indent}- {_scalar(child)}")


def render_json(record: Mapping[str, Any], mapping: Mapping[str, str], title: str) -> bytes:
    content = _at(record, mapping, "content") if "content" in mapping else _without(
        record, [mapping[name] for name in ("updated_at", "version") if name in mapping])
    if isinstance(content, str):
        body = content.replace("\r\n", "\n").strip()
    else:
        lines: list[str] = []
        _lines(content, 0, lines)
        body = "\n".join(lines)
    return f"# {title}\n\n{body[:MAX_BODY_CHARS]}\n".encode()


def item_content(record: Mapping[str, Any], mapping: Mapping[str, str], media_type: str, title: str) -> bytes:
    """The bytes of one record's content in its declared media type; a missing or wrong field is a contract fault."""
    if media_type == MEDIA_JSON:
        return render_json(record, mapping, title)
    value = _at(record, mapping, "content")
    if not isinstance(value, str) or not value.strip():
        raise ConnectorError(REASON_SOURCE_CONTRACT_VIOLATION)
    if media_type == "application/pdf":
        try:
            return base64.b64decode(value, validate=True)
        except (binascii.Error, ValueError):
            raise ConnectorError(REASON_SOURCE_CONTRACT_VIOLATION) from None
    return value.encode("utf-8")


__all__ = ["SKIP_UNVERSIONED", "SKIP_WITHOUT_ID", "RecordHeader", "external_id_of", "item_content", "record_header"]
