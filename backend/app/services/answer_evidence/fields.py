"""The source fields an evidence-bearing tool result item carries (imports nothing).

``source_title``, ``source_url`` and ``cite_as`` are the shape of a Knowledge passage; web and
connector results carry the same three (``tools/evidence_fields.py``). Result compressors that rebuild
items field by field keep them with :func:`source_subset`, so the model can cite what it reads and the
answer evidence guard (``evidence.py``) sees the sources.
"""

from __future__ import annotations

from typing import Any

SOURCE_FIELD_NAMES = ("source_title", "source_url", "cite_as")


def source_subset(item: object) -> dict[str, Any]:
    """The source fields ``item`` carries (non-null ones only)."""
    if not isinstance(item, dict):
        return {}
    return {name: item[name] for name in SOURCE_FIELD_NAMES if item.get(name) is not None}


__all__ = ["SOURCE_FIELD_NAMES", "source_subset"]
