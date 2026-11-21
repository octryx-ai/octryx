"""Which Confluence instance an item was actually read from.

A page's display/citation link may be built from the response's ``_links.base``, which the source controls; it is
never provenance. The provenance of a synced item is the base URL of the **connection the run read it through**
(``SourceItem.read_base``, set by the connector from its own reader), normalized to the instance identity
(``tools/_confluence_instance``) and stored on the ledger item (``knowledge_source_sync_items.source_instance``).

An item read from another instance than the one it was ingested from is fetched again, even at the same version
marker: a version number only identifies content within one instance.
"""

from __future__ import annotations

from .....tools._confluence_instance import confluence_instance
from .contract import SourceItem


def item_instance(item: SourceItem) -> str | None:
    """The instance the item was read from, ``None`` for a connector that reads no Confluence."""
    return confluence_instance(item.read_base) or None if item.read_base else None


def scope_connection(scoped, space_key: str):
    """The connection a run reads ``space_key`` through (``ScopeConnections``), ``None`` when none serves it."""
    wanted = str(space_key or "").upper()
    ref = next((ref for key, ref in scoped.by_key.items() if str(key).upper() == wanted), None)
    if ref is not None:
        return scoped.connections.get(ref)
    return scoped.single


__all__ = ["item_instance", "scope_connection"]
