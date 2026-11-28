"""The optional checked reply contract of an Agent Definition. ``{"kind": "text"}`` (the default) or ``{"kind":
"json_object", "schema": ...}``, whose reply must be one matching JSON object."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from .agent_reply_contract_schema import KIND_TEXT, REPLY_CONTRACT_FIELD, normalize_reply_contract, text_contract
from .agent_reply_contract_types import ReplyContract


def reply_contract_column(contract: Mapping[str, Any]) -> str | None:
    if contract.get("kind") == KIND_TEXT:
        return None
    return json.dumps(contract, ensure_ascii=False, separators=(",", ":"))


def declared_reply_contract(source: Mapping[str, Any], *keys: str) -> ReplyContract | None:
    for key in keys or (REPLY_CONTRACT_FIELD,):
        if key in source:
            return normalize_reply_contract(source[key])
    return None


def reply_contract_column_for_write(source: Mapping[str, Any], *, stored: str | None) -> str | None:
    # An invalid stored value is never kept silently: the save is refused instead.
    declared = declared_reply_contract(source, REPLY_CONTRACT_FIELD)
    if declared is not None:
        return reply_contract_column(declared)
    if stored is None:
        return None
    return reply_contract_column(normalize_reply_contract(live_row_reply_contract(stored)))


def live_row_reply_contract(column: Any) -> Any:
    # Unreadable text stays a string, so it fails closed.
    if column is None:
        return text_contract()
    try:
        return json.loads(column)
    except (TypeError, ValueError):
        return column


def snapshot_reply_contract_entry(column: Any) -> dict[str, Any]:
    return {} if column is None else {REPLY_CONTRACT_FIELD: live_row_reply_contract(column)}


def snapshot_reply_contract(header: Mapping[str, Any]) -> Any:
    return header[REPLY_CONTRACT_FIELD] if REPLY_CONTRACT_FIELD in header else text_contract()


__all__ = [
    "declared_reply_contract",
    "live_row_reply_contract",
    "reply_contract_column",
    "reply_contract_column_for_write",
    "snapshot_reply_contract",
    "snapshot_reply_contract_entry",
]
