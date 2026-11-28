"""The closed analyser of lexical retrieval: query terms, their word forms, and candidate tokens."""

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
    # ``casefold`` is locale-independent, which keeps the ordering the same everywhere.
    return unicodedata.normalize("NFKC", text).casefold()


def singular_of(word: str) -> str | None:
    if len(word) > 4 and word.endswith("ies"):
        return word[:-3] + "y"
    if len(word) > 4 and word.endswith(_SIBILANT_PLURAL):
        return word[:-2]
    if len(word) > 3 and word.endswith("s") and not word.endswith(_NOT_PLURAL):
        return word[:-1]
    return None


def word_forms(word: str) -> frozenset[str]:
    forms = {word}
    singular = singular_of(word)
    if singular is not None:
        forms.add(singular)
    if len(word) > 4 and word.endswith("ches"):
        forms.add(word[:-2])
    return frozenset(forms)


@dataclass(frozen=True, slots=True)
class QueryTerm:
    folded: str
    forms: frozenset[str]


def query_terms(query_text: str) -> tuple[QueryTerm, ...]:
    seen: dict[str, QueryTerm] = {}
    for token in content_terms(tuple(match.group(0) for match in _TERM.finditer(fold(query_text))), fold):
        if len(seen) >= MAX_RANKING_TERMS:
            break
        seen.setdefault(token, QueryTerm(token, word_forms(token)))
    return tuple(seen.values())


def candidate_tokens(body_text: str) -> frozenset[str]:
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
