"""Ordering the bounded lexical candidates: BM25 over the analysed tokens, weighted by tier-1 evidence.

The index publishes no relevance (``lexical_recall``), so the product orders the deduplicated union
of the plan's bounded fetches. The order is BM25 (``k1 = 1.2``, ``b = 0.75``) over the analysed
tokens of ``lexical_terms`` (folded words, identifier words, singular forms), with each term's
inverse document frequency estimated from what the plan saw:

- a term whose tier-1 fetches filled their cap, or that got no fetch (past the fetch budget), is
  common or unknown and weighs the least, ``ln 2``;
- otherwise its document frequency ``df`` is the larger of the records its fetches returned and the
  candidates its analysed forms match (the fetch counts index tokens; ranking also matches a plural
  or an identifier word, and ``df`` must count what ranking matches), and it weighs
  ``ln(1 + cap / df)``.

Length normalization keeps a long span (a message bundle, a SQL schema) from outranking a short
one only because it names more words. Ties break on the number of distinct terms, then on the
evidence key, so the order is total and deterministic. The score is internal and never published.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from .lexical_terms import QueryTerm, candidate_token_counts, term_frequency, word_forms

BM25_K1 = 1.2
BM25_B = 0.75
LEAST_WEIGHT = math.log(2.0)


@dataclass(frozen=True, slots=True)
class TermFetchEvidence:
    """What tier 1 saw of one folded term: how many records its fetches returned, and if any filled its cap."""

    records: int
    saturated: bool


def fetch_evidence(serves: Sequence[str], matched: Sequence[frozenset[str]], cap: int) -> dict[str, TermFetchEvidence]:
    """Per folded term, from the tier-1 fetches that serve it (``LexicalFetch.serves``)."""
    keys: dict[str, set[str]] = {}
    full: dict[str, bool] = {}
    for term, found in zip(serves, matched, strict=True):
        keys.setdefault(term, set()).update(found)
        full[term] = full.get(term, False) or len(found) >= cap
    return {term: TermFetchEvidence(len(keys[term]), full[term]) for term in keys}


def _weight(term: QueryTerm, evidence: Mapping[str, TermFetchEvidence] | None, pool_df: int, cap: int) -> float:
    if evidence is None:
        return 1.0
    seen = evidence.get(term.folded)
    if seen is None or seen.saturated:
        return LEAST_WEIGHT
    return math.log(1.0 + cap / max(1, seen.records, pool_df))


def rank_candidates(
    candidates: Mapping[str, str],
    terms: Sequence[QueryTerm | str],
    evidence: Mapping[str, TermFetchEvidence] | None = None,
    cap: int = 64,
) -> tuple[tuple[str, str], ...]:
    """Order the deduplicated union: BM25 first, then distinct terms, then the evidence key.

    A candidate is only ever ordered, never dropped: the server returned it, so it matched, and a
    zero-score candidate (possible when only a folded spelling differs) still sorts by its key
    rather than disappearing. Without ``evidence`` every term weighs the same.
    """
    analysed = [term if isinstance(term, QueryTerm) else QueryTerm(term, word_forms(term)) for term in terms if term]
    bodies = {key: candidate_token_counts(body) for key, body in candidates.items()}
    pool_df = {
        term.folded: sum(1 for counts, _ in bodies.values() if term_frequency(term, counts)) for term in analysed
    }
    weights = {term.folded: _weight(term, evidence, pool_df[term.folded], cap) for term in analysed}
    average = sum(length for _, length in bodies.values()) / max(1, len(bodies))
    scores: dict[str, tuple[float, int]] = {}
    for key, (counts, length) in bodies.items():
        norm = BM25_K1 * (1.0 - BM25_B + BM25_B * length / max(1.0, average))
        score, hits = 0.0, 0
        for term in analysed:
            tf = term_frequency(term, counts)
            if tf:
                hits += 1
                score += weights[term.folded] * tf * (BM25_K1 + 1.0) / (tf + norm)
        scores[key] = (score, hits)
    return tuple(sorted(candidates.items(), key=lambda item: (-scores[item[0]][0], -scores[item[0]][1], item[0])))


__all__ = ["BM25_B", "BM25_K1", "LEAST_WEIGHT", "TermFetchEvidence", "fetch_evidence", "rank_candidates"]
