"""The optional checked reply contract of an Agent Definition.

An agent replies in free text unless its author declares a checked JSON reply:

``{"kind": "text"}`` (default)
    Free text, unchecked. Agents, snapshots and packages without the key mean this.
``{"kind": "json_object", "schema": {...}}``
    The whole final reply must be one JSON object that matches the declared fields.

The schema is a bounded subset of the named schemas of ``agent_reply_contract_model``:
``type: "object"``, 1-32 ``properties`` named by its ``FieldName`` rule, each typed
``string``/``integer``/``number``/``boolean`` or an ``array`` of one of those, and ``required``
names that must be declared. Nothing else is accepted: no ``schemaRef``, ``enum``,
``description``, nested objects, other keywords, regex or code. As in JSON Schema, properties the
schema does not declare are allowed in a reply. Values are checked with ``matches_named``.

Key mapping (as for ``tool_surface``):

- database column ``reply_contract_json``: canonical JSON text, ``NULL`` for text;
- revision snapshot and export package: ``reply_contract``, omitted for text so existing
  checksums stay unchanged;
- runtime and panel read payload: ``replyContract``;
- panel write body: ``reply_contract`` or ``replyContract``.

Missing versus present:

- A missing key is text.
- A present value is validated as it is: writes, import and restore refuse it. ``null`` is
  never read as text.
- Projections carry a stored value verbatim, so publication validation refuses it and a runtime
  check fails closed with ``agent_reply_contract_invalid``.

Errors and check results never contain reply or contract content; only fixed codes.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from .agent_reply_contract_schema import KIND_TEXT, REPLY_CONTRACT_FIELD, normalize_reply_contract, text_contract

# --- storage and projections ---------------------------------------------------------------------------


def reply_contract_column(contract: Mapping[str, Any]) -> str | None:
    """The column value of a normalized contract: ``NULL`` for text, canonical JSON otherwise."""
    if contract.get("kind") == KIND_TEXT:
        return None
    return json.dumps(contract, ensure_ascii=False, separators=(",", ":"))


def declared_reply_contract(source: Mapping[str, Any], *keys: str) -> dict[str, Any] | None:
    """The normalized contract a write body, package or snapshot declares; ``None`` when no key is present.

    A present value, including ``null``, is validated as is (:class:`ReplyContractError`).
    """
    for key in keys or (REPLY_CONTRACT_FIELD,):
        if key in source:
            return normalize_reply_contract(source[key])
    return None


def reply_contract_column_for_write(source: Mapping[str, Any], *, stored: str | None) -> str | None:
    """The column a write stores: a declared key wins (validated); no key keeps *stored*.

    A stored value that is no longer valid is never kept by a write that does not choose a new
    one, so the save is refused instead (:class:`ReplyContractError`).
    """
    declared = declared_reply_contract(source, REPLY_CONTRACT_FIELD)
    if declared is not None:
        return reply_contract_column(declared)
    if stored is None:
        return None
    return reply_contract_column(normalize_reply_contract(live_row_reply_contract(stored)))


def live_row_reply_contract(column: Any) -> Any:
    """The stored contract, verbatim. ``NULL`` is text; unreadable text stays a string (fails closed)."""
    if column is None:
        return text_contract()
    try:
        return json.loads(column)
    except (TypeError, ValueError):
        return column


def snapshot_reply_contract_entry(column: Any) -> dict[str, Any]:
    """The snapshot/export key for a live row: omitted for text, otherwise the stored value verbatim."""
    return {} if column is None else {REPLY_CONTRACT_FIELD: live_row_reply_contract(column)}


def snapshot_reply_contract(header: Mapping[str, Any]) -> Any:
    """The runtime payload value of a snapshot header: missing means text, present is verbatim."""
    return header[REPLY_CONTRACT_FIELD] if REPLY_CONTRACT_FIELD in header else text_contract()


__all__ = [
    "declared_reply_contract",
    "live_row_reply_contract",
    "reply_contract_column",
    "reply_contract_column_for_write",
    "snapshot_reply_contract",
    "snapshot_reply_contract_entry",
]
