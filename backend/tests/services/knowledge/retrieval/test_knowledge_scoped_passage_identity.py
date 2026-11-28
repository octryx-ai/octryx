"""Contract: scoped fusion merges only the same passage (revision digest, character window and exact span
text), never a whole document; a real duplicate keeps the better-ranked provenance."""

from __future__ import annotations

from dataclasses import replace

import pytest

from app.services.knowledge.retrieval.evidence import CitedEvidence
from app.services.knowledge.retrieval.hybrid import HybridEvidence
from app.services.knowledge.retrieval.scoped import _fused

DIGEST = "b" * 64


def _hit(key, text, start, end, relevance=0.5, digest=DIGEST):
    span = CitedEvidence(evidence_key=key, text=text, citation=key, revision_id=key.split(":")[0],
                         span_ordinal=int(key.split(":")[1]), content_sha256=digest, source_title="Guide",
                         source_url=None, char_start=start, char_end=end)
    return HybridEvidence(span, ("lexical",), 0.02, None, relevance)


def _keys(result):
    return [(item.workspace_id, item.hit.evidence.evidence_key) for item in result]


@pytest.mark.parametrize("by_relevance", [True, False])
def test_same_text_at_another_place_is_a_different_passage(by_relevance):
    first = _hit("r:1", "Use Jackson 3", 10, 23, 0.9)
    elsewhere = _hit("r:9", "Use Jackson 3", 400, 413, 0.8)
    assert len(_fused([("own", "Own", (first, elsewhere))], by_relevance=by_relevance)) == 2


def test_different_text_in_the_same_window_is_a_different_passage():
    first = _hit("r:1", "Use Jackson 3", 10, 23, 0.9)
    other = _hit("s:1", "Use Gson instead", 10, 23, 0.8)
    assert len(_fused([("own", "Own", (first, other))], by_relevance=True)) == 2


@pytest.mark.parametrize(
    ("start", "end", "digest"),
    [(0, 0, DIGEST), (20, 10, DIGEST), (-1, 5, DIGEST), (0, 13, ""), (0, 13, "b" * 63), (0, 13, "B" * 64)],
)
def test_a_missing_or_invalid_locator_never_merges(start, end, digest):
    first = _hit("r:1", "Use Jackson 3", start, end, 0.9, digest)
    copy = _hit("c:1", "Use Jackson 3", start, end, 0.8, digest)
    result = _fused([("own", "Own", (first,)), ("library", "Library", (copy,))], by_relevance=True)
    assert _keys(result) == [("own", "r:1"), ("library", "c:1")]


def test_the_same_key_without_a_locator_in_two_workspaces_stays_two_hits():
    first = _hit("r:1", "Text", 0, 0, 0.9)
    result = _fused([("own", "Own", (first,)), ("library", "Library", (first,))], by_relevance=True)
    assert len(result) == 2


def test_a_real_duplicate_keeps_the_better_ranked_provenance_in_both_modes():
    own = _hit("r:65", "Default JSON library", 100, 120, 0.7)
    library = replace(_hit("c:65", "Default JSON library", 100, 120, 0.9))
    by_relevance = _fused([("own", "Own", (own,)), ("library", "Library", (library,))], by_relevance=True)
    assert _keys(by_relevance) == [("library", "c:65")], "higher relevance wins"
    by_rank = _fused([("own", "Own", (own,)), ("library", "Library", (library,))], by_relevance=False)
    assert _keys(by_rank) == [("own", "r:65")], "equal RRF rank: the first Workspace in scope order"


def test_non_duplicates_keep_their_ranking_order():
    hits = tuple(_hit(f"r:{n}", f"Passage {n}", n * 100, n * 100 + 9, 0.9 - n / 10) for n in range(1, 5))
    assert _keys(_fused([("own", "Own", hits)], by_relevance=True)) == [("own", f"r:{n}") for n in range(1, 5)]
    assert _keys(_fused([("own", "Own", hits)], by_relevance=False)) == [("own", f"r:{n}") for n in range(1, 5)]
