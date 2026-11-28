"""A page's location is proven only by a complete ancestor chain; one unusable entry makes the parent unknown rather
than promoting the ancestor above it."""

from __future__ import annotations

from app.tools._confluence_access import complete_ancestor_ids

BROKEN = [{"type": "page"}, {"id": None}, {"id": ""}, {"id": "abc"}, "901", {"id": True}]


def test_complete_ancestor_ids_never_filters():
    assert complete_ancestor_ids({"ancestors": []}) == []
    assert complete_ancestor_ids({"ancestors": [{"id": "900"}, {"id": 901}]}) == ["900", "901"]
    for entry in BROKEN:
        assert complete_ancestor_ids({"ancestors": [{"id": "900"}, entry]}) is None, entry
    assert complete_ancestor_ids({}) is None and complete_ancestor_ids({"ancestors": None}) is None
