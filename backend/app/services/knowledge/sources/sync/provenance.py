"""Which Confluence instance an item was actually read from. The response's ``_links.base`` is never provenance; the
run's connection is."""

from __future__ import annotations

from .....tools._confluence_instance import confluence_instance
from .contract import SourceItem


def item_instance(item: SourceItem) -> str | None:
    return confluence_instance(item.read_base) or None if item.read_base else None


def scope_connection(scoped, space_key: str):
    wanted = str(space_key or "").upper()
    ref = next((ref for key, ref in scoped.by_key.items() if str(key).upper() == wanted), None)
    if ref is not None:
        return scoped.connections.get(ref)
    return scoped.single


__all__ = ["item_instance", "scope_connection"]
