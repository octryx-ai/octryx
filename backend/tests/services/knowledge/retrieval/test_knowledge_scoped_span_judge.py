"""Independent root probes: source-level dedup must not discard distinct evidence spans."""
from dataclasses import replace

from app.services.knowledge.retrieval.evidence import CitedEvidence
from app.services.knowledge.retrieval.hybrid import HybridEvidence
from app.services.knowledge.retrieval.scoped import _fused


def hit(key, ordinal, text, start, end, relevance):
    span = CitedEvidence(evidence_key=key, text=text, citation=key,
                         revision_id=key.split(":")[0], span_ordinal=ordinal,
                         content_sha256="a" * 64, source_title="Migration guide", source_url=None,
                         char_start=start, char_end=end)
    return HybridEvidence(span, ("lexical", "vector"), 0.03, 0.8, relevance)


def test_two_complementary_passages_of_one_document_both_survive():
    first = hit("rev:68", 68, "Compatibility setting", 200, 221, 0.9)
    second = hit("rev:65", 65, "Default library", 100, 115, 0.8)
    for by_relevance in (True, False):
        result = _fused([("own", "Own", (first, second))], by_relevance=by_relevance)
        assert [x.hit.evidence.evidence_key for x in result] == ["rev:68", "rev:65"]


def test_same_passage_across_workspaces_deduplicates_with_best_provenance():
    first = hit("rev:65", 65, "Default library", 100, 115, 0.9)
    duplicate = replace(first, evidence=replace(first.evidence, evidence_key="copy:65", revision_id="copy"),
                        relevance=0.8)
    result = _fused([("own", "Own", (first,)), ("library", "Library", (duplicate,))], by_relevance=True)
    assert len(result) == 1 and result[0].workspace_id == "own"


def test_same_ordinal_in_different_segmentations_is_not_a_duplicate():
    first = hit("rev:1", 1, "First paragraph", 0, 15, 0.9)
    different = hit("other:1", 1, "First and second paragraph", 0, 26, 0.8)
    result = _fused([("own", "Own", (first, different))], by_relevance=True)
    assert len(result) == 2
