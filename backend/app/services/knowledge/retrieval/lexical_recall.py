"""Bounded lexical recall: a plan of index fetches whose size depends only on the query.

Every fetch is a registry operation with its own server-side ``LIMIT :cap``, so a fetch whose match
set is larger than the cap returns only the best-matching slice of it (``postgres_statements``).

- **Tier 1, one fetch per term form.** Each content term of the query (at most
  :data:`MAX_FETCH_TERMS`) is fetched by its raw spelling, and by its singular when it has one
  (``lexical_terms.singular_of``), at most :data:`MAX_SINGLE_FETCHES` fetches. A fetch that
  returns fewer rows than the cap has returned its **whole** match set.
- **Tier 2, one conjunctive fetch per pair of saturated terms.** A record whose every term is over
  the cap can be cut from every tier-1 fetch; a conjunction of two terms is far more selective than
  either. Tier 2 runs after tier 1 and only for terms whose tier-1 fetch filled its cap, so the
  budget goes where truncation happened. At most :data:`MAX_PAIR_FETCHES` pairs, in
  ``itertools.combinations`` order of the saturated terms in query order.

Both tiers are corpus-independent in their bound: the plan length depends only on the query, never
on how many records match (:data:`MAX_FETCHES`), and every fetch carries the same server-owned cap.

**Ranking** is product-owned and a total order (``lexical_ranking``): BM25 over the analysed tokens
of ``lexical_terms``, each term weighed by how selective tier 1 found it. The score stays internal
and is never published.

Fetch terms are raw: the index matches whole tokens as it analysed them. Duplicates are removed by
folded form (the match is case-insensitive) while the first raw spelling is what travels, so
``Alpha alpha`` spends one fetch, not two.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from itertools import combinations

from ..access.acl_keys import PUBLIC_ACL_KEY
from ..evidence_index.operations import (
    SEARCH_EVIDENCE_LEXICAL,
    SEARCH_EVIDENCE_LEXICAL_PAIR,
    SEARCH_EVIDENCE_LEXICAL_PAIR_SCOPED,
    SEARCH_EVIDENCE_LEXICAL_PAIR_SCOPED_VERSION,
    SEARCH_EVIDENCE_LEXICAL_SCOPED,
    SEARCH_EVIDENCE_LEXICAL_SCOPED_VERSION,
)
from .errors import KnowledgeStoreContractError
from .lexical_terms import fold, query_terms, singular_of
from .stop_words import content_terms

CANDIDATE_MULTIPLIER = 4
MAX_CANDIDATES = 64
# Content terms that get fetches of their own; a later term still ranks.
MAX_FETCH_TERMS = 6
# Tier 1: a term's raw spelling and its singular form are separate fetches.
MAX_SINGLE_FETCHES = 10
# Tier 2: pairs of saturated terms; the first four saturated terms in query order make six.
MAX_PAIR_FETCHES = 6
MAX_FETCHES = MAX_SINGLE_FETCHES + MAX_PAIR_FETCHES
# Fetch tokens. ``\w`` is Unicode-aware for ``str`` patterns, so a non-ASCII word is one term.
_TERM = re.compile(r"\w+", re.UNICODE)

# The registry operation and its declared parameter names, per fetch arity. A fetch
# can therefore only ever produce exactly the parameter set its operation declares.
_OPERATIONS: Mapping[int, str] = {1: SEARCH_EVIDENCE_LEXICAL, 2: SEARCH_EVIDENCE_LEXICAL_PAIR}
# The same fetches narrowed to a product scope, and to a product scope plus a subject version.
_SCOPED_OPERATIONS: Mapping[tuple[int, bool], str] = {
    (1, False): SEARCH_EVIDENCE_LEXICAL_SCOPED,
    (2, False): SEARCH_EVIDENCE_LEXICAL_PAIR_SCOPED,
    (1, True): SEARCH_EVIDENCE_LEXICAL_SCOPED_VERSION,
    (2, True): SEARCH_EVIDENCE_LEXICAL_PAIR_SCOPED_VERSION,
}
_PARAMETER_NAMES: Mapping[int, tuple[str, ...]] = {1: ("term",), 2: ("term_a", "term_b")}


def candidate_cap(limit_per_mode: int) -> int:
    """The server-owned ``LIMIT`` every fetch of the plan carries."""
    if type(limit_per_mode) is not int or limit_per_mode < 1:
        raise KnowledgeStoreContractError()
    return min(limit_per_mode * CANDIDATE_MULTIPLIER, MAX_CANDIDATES)


def ranking_terms(query_text: str) -> tuple[str, ...]:
    """Distinct folded content terms of the query, in order, at most ``MAX_RANKING_TERMS``."""
    return tuple(term.folded for term in query_terms(query_text))


def fetch_terms(query_text: str) -> tuple[str, ...]:
    """Distinct raw content terms that get fetches of their own, at most ``MAX_FETCH_TERMS``.

    Raw, because the value must match the text as the index analysed it. Deduplicated
    by folded form because the match is case-insensitive, so two spellings of
    one word would otherwise spend two fetches on the same match set.
    """
    seen: dict[str, str] = {}
    # Function words first leave the query, so the fetches go to the terms that carry it.
    for token in content_terms(tuple(match.group(0) for match in _TERM.finditer(query_text)), fold):
        if len(seen) >= MAX_FETCH_TERMS:
            break
        seen.setdefault(fold(token), token)
    return tuple(seen.values())


@dataclass(frozen=True, slots=True)
class LexicalFetch:
    """One bounded, index-backed fetch: the terms decide which operation it is."""

    terms: tuple[str, ...]
    products: tuple[str, ...] = ()
    version: str | None = None
    # The source ACL keys the request admits; every fetch filters on them.
    acl_keys: tuple[str, ...] = (PUBLIC_ACL_KEY,)
    # The folded query term a tier-1 fetch serves (its raw spelling or its singular form).
    serves: str = ""

    def __post_init__(self) -> None:
        if type(self.terms) is not tuple or len(self.terms) not in _OPERATIONS:
            raise KnowledgeStoreContractError()
        if not all(type(term) is str and term for term in self.terms):
            raise KnowledgeStoreContractError()

    @property
    def operation(self) -> str:
        """The registry key this fetch runs; never statement text."""
        if self.products:
            return _SCOPED_OPERATIONS[(len(self.terms), self.version is not None)]
        return _OPERATIONS[len(self.terms)]

    def parameters(self, cap: int) -> dict[str, object]:
        """Exactly the parameter names the operation declares, plus its bound."""
        parameters: dict[str, object] = dict(zip(_PARAMETER_NAMES[len(self.terms)], self.terms, strict=True))
        parameters["cap"] = cap
        parameters["principals"] = list(self.acl_keys)
        if self.products:
            parameters["products"] = list(self.products)
            if self.version is not None:
                parameters["version"] = self.version
        return parameters


def fetch_plan(
    query_text: str,
    products: tuple[str, ...] = (),
    version: str | None = None,
    acl_keys: tuple[str, ...] = (PUBLIC_ACL_KEY,),
) -> tuple[LexicalFetch, ...]:
    """Tier 1 of one lexical query: one fetch per term, then its singular form, bounded.

    Deterministic and corpus-independent. An empty plan means the query text carries
    no word token at all.
    """
    plan: list[LexicalFetch] = []
    for raw in fetch_terms(query_text):
        folded = fold(raw)
        singular = singular_of(folded)
        for spelling in (raw, singular):
            if spelling is not None and len(plan) < MAX_SINGLE_FETCHES:
                plan.append(LexicalFetch((spelling,), products, version, acl_keys, folded))
    return tuple(plan)


def pair_plan(singles: Sequence[LexicalFetch], saturated: Sequence[bool]) -> tuple[LexicalFetch, ...]:
    """Tier 2: one conjunctive fetch per pair of terms whose every tier-1 fetch filled its cap."""
    if not singles:
        return ()
    fills: dict[str, bool] = {}
    spelling: dict[str, str] = {}
    for fetch, full in zip(singles, saturated, strict=True):
        fills[fetch.serves] = fills.get(fetch.serves, True) and full
        spelling.setdefault(fetch.serves, fetch.terms[0])
    over = [term for term, full in fills.items() if full]
    head = singles[0]
    pairs = [
        LexicalFetch((spelling[a], spelling[b]), head.products, head.version, head.acl_keys)
        for a, b in combinations(over, 2)
    ]
    return tuple(pairs[:MAX_PAIR_FETCHES])


__all__ = [
    "CANDIDATE_MULTIPLIER",
    "MAX_CANDIDATES",
    "MAX_FETCHES",
    "MAX_FETCH_TERMS",
    "MAX_PAIR_FETCHES",
    "MAX_SINGLE_FETCHES",
    "LexicalFetch",
    "candidate_cap",
    "fetch_plan",
    "fetch_terms",
    "pair_plan",
    "ranking_terms",
]
