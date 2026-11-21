"""The closed analyser of lexical retrieval: query terms, their word forms, and candidate tokens.

A fixed text normalization, the same for every query and every Workspace; it never reads intent.

- **Content terms** are the query's word tokens without function words (``stop_words``), folded
  (``NFKC`` plus ``casefold``) and deduplicated in query order.
- **Word forms** fold an English plural onto its singular, the one inflection that decides whether
  a question about "entities", "pets" or "repositories" reaches the ``@Entity``, ``Pet`` and
  ``OwnerRepository`` it names. The rules are closed and symmetric: a query
  term and a candidate token match when their form sets share a member, so "drill" still reaches
  "drills". Nothing else is stemmed.
- **Candidate tokens** are a candidate body's word tokens, folded, plus the words of its compound
  identifiers (``initCreationForm`` -> init, creation, form; ``vet_specialties`` -> vet,
  specialties), so ranking reads identifiers the way a code span's retrieval text indexes them.

Ranking (``lexical_recall.rank_candidates``) uses these tokens; fetching uses the raw spelling of a
term and its singular form, because the index matches whole tokens as it analysed them.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from ..code.retrieval_text import identifier_words
from .stop_words import content_terms

MAX_RANKING_TERMS = 32
# ``\\w`` is Unicode-aware for ``str`` patterns, so a non-ASCII word is one term instead of being
# split into its ASCII runs.
_TERM = re.compile(r"\w+", re.UNICODE)
_SIBILANT_PLURAL = ("sses", "shes", "xes", "zes")
_NOT_PLURAL = ("ss", "us", "is")


def fold(text: str) -> str:
    """The one comparison form for ranking: ``NFKC`` plus ``casefold``.

    Applied to the query and to every candidate body, so a match that only differs
    in composition or case is a hit on both sides or on neither. ``casefold`` is
    locale-independent, which is what keeps the ordering the same everywhere.
    """
    return unicodedata.normalize("NFKC", text).casefold()


def singular_of(word: str) -> str | None:
    """The singular of a folded English plural (``entities`` -> ``entity``), else ``None``."""
    if len(word) > 4 and word.endswith("ies"):
        return word[:-3] + "y"
    if len(word) > 4 and word.endswith(_SIBILANT_PLURAL):
        return word[:-2]
    if len(word) > 3 and word.endswith("s") and not word.endswith(_NOT_PLURAL):
        return word[:-1]
    return None


def word_forms(word: str) -> frozenset[str]:
    """``word`` and the singular forms it may stand for (``caches`` -> caches, cache, cach)."""
    forms = {word}
    singular = singular_of(word)
    if singular is not None:
        forms.add(singular)
    if len(word) > 4 and word.endswith("ches"):
        forms.add(word[:-2])
    return frozenset(forms)


@dataclass(frozen=True, slots=True)
class QueryTerm:
    """One folded content term of a query and the forms a candidate token may match it by."""

    folded: str
    forms: frozenset[str]


def query_terms(query_text: str) -> tuple[QueryTerm, ...]:
    """Distinct folded content terms of the query, in order, at most ``MAX_RANKING_TERMS``."""
    seen: dict[str, QueryTerm] = {}
    for token in content_terms(tuple(match.group(0) for match in _TERM.finditer(fold(query_text))), fold):
        if len(seen) >= MAX_RANKING_TERMS:
            break
        seen.setdefault(token, QueryTerm(token, word_forms(token)))
    return tuple(seen.values())


def candidate_tokens(body_text: str) -> frozenset[str]:
    """Every form a candidate body can be matched by: folded tokens, identifier words, singulars."""
    tokens: set[str] = set()
    for match in _TERM.finditer(body_text):
        raw = match.group(0)
        tokens.add(fold(raw))
        tokens.update(fold(word) for word in identifier_words(raw))
    forms: set[str] = set()
    for token in tokens:
        forms |= word_forms(token)
    return frozenset(forms)


def candidate_token_counts(body_text: str) -> tuple[dict[str, int], int]:
    """How often each form occurs in a candidate body, and the body's length in word tokens."""
    counts: dict[str, int] = {}
    length = 0
    for match in _TERM.finditer(body_text):
        raw = match.group(0)
        length += 1
        forms: set[str] = set(word_forms(fold(raw)))
        for word in identifier_words(raw):
            forms |= word_forms(fold(word))
        for form in forms:
            counts[form] = counts.get(form, 0) + 1
    return counts, length


def term_frequency(term: QueryTerm, counts: dict[str, int]) -> int:
    return max((counts.get(form, 0) for form in term.forms), default=0)


def term_matches(term: QueryTerm, tokens: frozenset[str]) -> bool:
    return not term.forms.isdisjoint(tokens)


__all__ = [
    "MAX_RANKING_TERMS",
    "QueryTerm",
    "candidate_tokens",
    "fold",
    "query_terms",
    "singular_of",
    "term_matches",
    "word_forms",
]
