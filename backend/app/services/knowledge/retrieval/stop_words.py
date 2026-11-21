"""Function words that carry no retrieval signal (English), for lexical recall.

The lexical plan fetches at most a few terms per query, so a question such as "When is the
failover drill?" must not spend that budget on "when", "is" and "the". This is fixed text
normalization, not intent detection: the list is closed, and a query made only of function words
keeps them, so no query is emptied by the filter.
"""

from __future__ import annotations

STOP_WORDS = frozenset(
    """
    a about above after again against all am an and any are as at be because been before being
    below between both but by can could did do does doing down during each few for from further
    had has have having he her here hers herself him himself his how i if in into is it its itself
    just me more most my myself no nor not now of off on once only or other our ours ourselves out
    over own same she should so some such than that the their theirs them themselves then there
    these they this those through to too under until up very was we were what when where which
    while who whom why will with would you your yours yourself yourselves please tell show give
    """.split()
)


def content_terms(terms: tuple[str, ...], fold) -> tuple[str, ...]:
    """``terms`` without function words, compared in folded form; all of them when nothing remains."""
    kept = tuple(term for term in terms if fold(term) not in STOP_WORDS)
    return kept or terms


__all__ = ["STOP_WORDS", "content_terms"]
