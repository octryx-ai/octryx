"""One retry hint on a search that found nothing.

A model that searches once with several overloaded keywords, gets no match and answers "no results" misses
items a second search with one keyword finds. So an empty search result says, once, what to try before
concluding that nothing exists. It is a hint in the result, never a refusal or an automatic retry.
"""

from __future__ import annotations

from typing import Any

EMPTY_SEARCH_HINT = (
    "No match. Before answering that nothing exists, search once more with a single keyword (in the language of the "
    "titles, often English) or without filters."
)


def with_empty_search_hint(result: dict[str, Any], *, items_key: str = "results") -> dict[str, Any]:
    """``result`` plus ``next_step`` when its ``items_key`` list is empty; unchanged otherwise."""
    items = result.get(items_key)
    if isinstance(items, list) and not items:
        return {**result, "next_step": EMPTY_SEARCH_HINT}
    return result


__all__ = ["EMPTY_SEARCH_HINT", "with_empty_search_hint"]
