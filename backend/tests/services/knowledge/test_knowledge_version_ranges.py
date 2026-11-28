"""A version bound names a release line at its own precision (Knowledge, A1)."""

from __future__ import annotations

from app.services.knowledge.temporal.versions import in_range, is_empty_range


def test_major_bounds_cover_whole_release_lines():
    assert in_range("4.0", after="3", through="4")
    assert in_range("4.1.2", after="3", through="4")
    assert not in_range("3.5", after="3", through="4")
    assert not in_range("5.0", after="3", through="4")


def test_minor_bounds_keep_patches_with_their_line():
    assert in_range("4.0", after="3.5", through="4.0")
    assert in_range("4.0.1", after="3.5", through="4.0")
    assert not in_range("3.5.1", after="3.5", through="4.0")
    assert not in_range("4.1", after="3.5", through="4.0")
    assert in_range("2.4.20", after="2.4.19", through="2.4.20")


def test_a_range_whose_upper_line_does_not_follow_the_lower_is_empty():
    assert is_empty_range("3", "3.5")
    assert is_empty_range("4.0", "4")
    assert not is_empty_range("3", "4")
    assert not is_empty_range("3.5", "4.0")
