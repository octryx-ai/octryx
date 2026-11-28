"""Bounded lexical recall: a plan of index fetches whose size depends only on the query."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from itertools import combinations

from ..access.acl_keys import PUBLIC_ACL_KEY, AclKey
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
    if type(limit_per_mode) is not int or limit_per_mode < 1:
        raise KnowledgeStoreContractError()
    return min(limit_per_mode * CANDIDATE_MULTIPLIER, MAX_CANDIDATES)


def ranking_terms(query_text: str) -> tuple[str, ...]:
    return tuple(term.folded for term in query_terms(query_text))


def fetch_terms(query_text: str) -> tuple[str, ...]:
    # Raw terms: the value must match the text as the index analysed it.
    seen: dict[str, str] = {}
    # Function words first leave the query, so the fetches go to the terms that carry it.
    for token in content_terms(tuple(match.group(0) for match in _TERM.finditer(query_text)), fold):
        if len(seen) >= MAX_FETCH_TERMS:
            break
        seen.setdefault(fold(token), token)
    return tuple(seen.values())


@dataclass(frozen=True, slots=True)
class LexicalFetch:
    terms: tuple[str, ...]
    products: tuple[str, ...] = ()
    version: str | None = None
    # The source ACL keys the request admits; every fetch filters on them.
    acl_keys: tuple[AclKey, ...] = (PUBLIC_ACL_KEY,)
    # The folded query term a tier-1 fetch serves (its raw spelling or its singular form).
    serves: str = ""

    def __post_init__(self) -> None:
        if type(self.terms) is not tuple or len(self.terms) not in _OPERATIONS:
            raise KnowledgeStoreContractError()
        if not all(type(term) is str and term for term in self.terms):
            raise KnowledgeStoreContractError()

    @property
    def operation(self) -> str:
        if self.products:
            return _SCOPED_OPERATIONS[(len(self.terms), self.version is not None)]
        return _OPERATIONS[len(self.terms)]

    def parameters(self, cap: int) -> dict[str, object]:
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
    acl_keys: tuple[AclKey, ...] = (PUBLIC_ACL_KEY,),
) -> tuple[LexicalFetch, ...]:
    plan: list[LexicalFetch] = []
    for raw in fetch_terms(query_text):
        folded = fold(raw)
        singular = singular_of(folded)
        for spelling in (raw, singular):
            if spelling is not None and len(plan) < MAX_SINGLE_FETCHES:
                plan.append(LexicalFetch((spelling,), products, version, acl_keys, folded))
    return tuple(plan)


def pair_plan(singles: Sequence[LexicalFetch], saturated: Sequence[bool]) -> tuple[LexicalFetch, ...]:
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
