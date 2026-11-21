"""Retrieval metrics for one configuration over a golden set.

A retrieved hit is correct when it cites the expected source and its text contains the expected
passage (case-insensitive). Per query the metric is the rank of the first correct hit.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class QueryOutcome:
    query_id: str
    lang: str
    first_correct_rank: int | None
    returned: int
    latency_ms: float
    state: str = "ok"


@dataclass(slots=True)
class ConfigurationReport:
    name: str
    outcomes: list[QueryOutcome] = field(default_factory=list)

    def summary(self) -> dict[str, object]:
        answered = [outcome for outcome in self.outcomes if outcome.state == "ok"]
        total = len(self.outcomes) or 1
        ranks = [outcome.first_correct_rank for outcome in self.outcomes]
        latencies = sorted(outcome.latency_ms for outcome in answered) or [0.0]

        def share(predicate) -> float:
            return round(sum(1 for rank in ranks if predicate(rank)) / total, 3)

        return {
            "configuration": self.name,
            "queries": len(self.outcomes),
            "failed": len(self.outcomes) - len(answered),
            "hit@1": share(lambda rank: rank == 1),
            "recall@5": share(lambda rank: rank is not None and rank <= 5),
            "mrr@10": round(sum(1 / rank for rank in ranks if rank is not None and rank <= 10) / total, 3),
            "de_hit@1": _lang_share(self.outcomes, "de"),
            "en_hit@1": _lang_share(self.outcomes, "en"),
            "p50_ms": round(latencies[len(latencies) // 2], 1),
            "p95_ms": round(latencies[min(len(latencies) - 1, int(len(latencies) * 0.95))], 1),
            "misses": [outcome.query_id for outcome in self.outcomes if outcome.first_correct_rank is None],
        }


def _lang_share(outcomes: list[QueryOutcome], lang: str) -> float:
    subset = [outcome for outcome in outcomes if outcome.lang == lang]
    if not subset:
        return 0.0
    return round(sum(1 for outcome in subset if outcome.first_correct_rank == 1) / len(subset), 3)


def first_correct_rank(hits: list[tuple[str, str]], *, source_title: str, passage: str) -> int | None:
    """1-based rank of the first ``(source_title, text)`` hit that is the expected evidence."""
    needle = passage.casefold()
    for rank, (title, text) in enumerate(hits, start=1):
        if title == source_title and needle in text.casefold():
            return rank
    return None


__all__ = ["ConfigurationReport", "QueryOutcome", "first_correct_rank"]
