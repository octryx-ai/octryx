"""The evaluation harness judges hits by source and passage, and its golden sets are well-formed."""

from __future__ import annotations

from app.services.knowledge.eval.golden import load_golden_set
from app.services.knowledge.eval.metrics import ConfigurationReport, QueryOutcome, first_correct_rank


def test_a_hit_counts_only_with_the_right_source_and_the_right_passage() -> None:
    hits = [
        ("Other", "requires Java 17 or later"),
        ("Guide", "nothing here"),
        ("Guide", "It REQUIRES JAVA 17 or later."),
    ]
    assert first_correct_rank(hits, source_title="Guide", passage="requires Java 17 or later") == 3
    assert first_correct_rank(hits[:2], source_title="Guide", passage="requires Java 17 or later") is None


def test_the_summary_reports_rank_metrics_per_language() -> None:
    report = ConfigurationReport(name="x")
    report.outcomes += [
        QueryOutcome("a", "en", 1, 5, 10.0),
        QueryOutcome("b", "de", 3, 5, 20.0),
        QueryOutcome("c", "de", None, 0, 30.0),
    ]
    summary = report.summary()
    assert summary["hit@1"] == 0.333 and summary["recall@5"] == 0.667
    assert summary["mrr@10"] == round((1 + 1 / 3) / 3, 3)
    assert summary["en_hit@1"] == 1.0 and summary["de_hit@1"] == 0.0 and summary["misses"] == ["c"]


def test_the_spring_boot_golden_set_is_well_formed() -> None:
    golden = load_golden_set("spring_boot")
    assert len(golden.queries) >= 25
    assert {query.lang for query in golden.queries} == {"en", "de"}
    assert all(query.passage.strip() and query.source in golden.sources for query in golden.queries)
    assert all(source.url.startswith("https://") for source in golden.sources.values())
