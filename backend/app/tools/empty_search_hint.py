"""One retry hint on a search that found nothing."""

from __future__ import annotations

from typing import Any

EMPTY_SEARCH_HINT = (
    "No match. Before answering that nothing exists, search once more with a single keyword (in the language of the "
    "titles, often English) or without filters."
)


def with_empty_search_hint(result: dict[str, Any], *, items_key: str = "results") -> dict[str, Any]:
    items = result.get(items_key)
    if isinstance(items, list) and not items:
        return {**result, "next_step": EMPTY_SEARCH_HINT}
    return result


__all__ = ["EMPTY_SEARCH_HINT", "with_empty_search_hint"]
