"""A page's location is proven only by a complete ancestor chain.

``complete_ancestor_ids`` validates every entry: one entry without a usable id makes the parent **unknown** — it is
never filtered away, which would promote the ancestor above it to direct parent. A valid ``[]`` stays the proven
space root; a complete chain keeps its last element as the direct parent.
"""

from __future__ import annotations

from app.tools._confluence_access import complete_ancestor_ids

BROKEN = [{"type": "page"}, {"id": None}, {"id": ""}, {"id": "abc"}, "901", {"id": True}]


def test_complete_ancestor_ids_never_filters():
    assert complete_ancestor_ids({"ancestors": []}) == []
    assert complete_ancestor_ids({"ancestors": [{"id": "900"}, {"id": 901}]}) == ["900", "901"]
    for entry in BROKEN:
        assert complete_ancestor_ids({"ancestors": [{"id": "900"}, entry]}) is None, entry
    assert complete_ancestor_ids({}) is None and complete_ancestor_ids({"ancestors": None}) is None
