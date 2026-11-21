"""The PR review bot, measured (concept §6: "the real values we measure in the first operation").

Counted in-process at the event, never from a database query:

- ``octryx_pr_review_bot_triggers_total{trigger,provider,outcome,reason}``: every pull request head a webhook or the
  hourly sync handed to the bot, with what the bot did (``started``, ``already_reviewed``, ``skipped`` and why);
- ``octryx_pr_review_bot_reviews_total{provider,verdict,result}``: every review posted (``posted``) or that could
  not be posted (``failed``), by the reviewer's verdict (``pass`` / ``changes`` / ``none``);
- ``octryx_pr_review_bot_findings_total{provider,severity,placement}``: the findings posted, ``inline`` on a diff
  line or in the ``summary`` (a line outside the diff: GitHub refuses a review comment there);
- ``octryx_pr_review_bot_finding_outcomes_total{provider,repo,severity,outcome}``: what became of them,
  counted when it happens: ``fixed`` (a later pass found it fixed), ``suggestion_applied`` (fixed by applying its
  suggestion), ``ignored`` (``@octryx ignore``), ``open_at_close`` (still open when the pull request left the open
  list). ``repo`` is a short hash of the repository, never its name; no pull request number (cardinality).

Imports only the standard library and ``metric_types`` (``agent_metrics`` imports it at ``db/core.py`` import time).
"""

from __future__ import annotations

from .metric_types import Counter, _Metric

TRIGGERS = Counter("octryx_pr_review_bot_triggers_total", "Pull request heads handed to the review bot by trigger"
                   " (webhook, sync), provider and outcome (started, already_reviewed, skipped) with the skip reason",
                   ("trigger", "provider", "outcome", "reason"))
REVIEWS = Counter("octryx_pr_review_bot_reviews_total", "Reviews the bot posted (posted) or could not post (failed),"
                  " by provider and verdict (pass, changes, none)", ("provider", "verdict", "result"))
FINDINGS = Counter("octryx_pr_review_bot_findings_total", "Findings the bot posted by provider, severity and"
                   " placement (inline on a diff line, summary otherwise)", ("provider", "severity", "placement"))

OUTCOMES = Counter("octryx_pr_review_bot_finding_outcomes_total", "What became of the findings the bot posted, by"
                   " provider, repository key, severity and outcome (fixed, suggestion_applied, ignored,"
                   " open_at_close)", ("provider", "repo", "severity", "outcome"))
FINDING_OUTCOMES = ("fixed", "suggestion_applied", "ignored", "open_at_close")

METRICS: tuple[_Metric, ...] = (TRIGGERS, REVIEWS, FINDINGS, OUTCOMES)


def repo_key(repository: str) -> str:
    """A short stable label for a repository (``github:owner/repo``): never its name (no free text in a label)."""
    import hashlib

    return hashlib.sha1(repository.strip().lower().encode()).hexdigest()[:8] if repository else "unknown"


def prime_outcomes(provider: str, repository: str) -> None:
    """Every outcome × severity of a repository at 0 (``increase()`` needs two points, so the
    first real outcome of a series that did not exist yet would show no data). Idempotent; called when a review
    posts."""
    for severity in ("high", "medium", "low"):
        for outcome in FINDING_OUTCOMES:
            key = OUTCOMES._key({"provider": provider or "unknown", "repo": repo_key(repository),
                                 "severity": severity, "outcome": outcome})
            OUTCOMES.series.setdefault(key, 0)


def count_outcome(provider: str, repository: str, severity: str, outcome: str) -> None:
    """One finding's outcome (F3: the bot's precision is (fixed + suggestion_applied) / (those + ignored))."""
    if outcome in FINDING_OUTCOMES:
        OUTCOMES.inc(provider=provider or "unknown", repo=repo_key(repository),
                     severity=severity if severity in ("high", "medium", "low") else "unknown", outcome=outcome)


def reset() -> None:
    """Tests: start empty."""
    for metric in METRICS:
        metric.series.clear()


def count_trigger(trigger: str, provider: str, outcome: str, reason: str = "") -> None:
    TRIGGERS.inc(trigger=trigger, provider=provider or "unknown", outcome=outcome, reason=reason or "none")


def count_review(provider: str, verdict: str, result: str) -> None:
    REVIEWS.inc(provider=provider or "unknown", verdict=verdict or "none", result=result)


def count_findings(provider: str, placed: list[tuple[str, str]], repository: str = "") -> None:
    """``placed``: ``(severity, placement)`` per posted finding; a posted review of ``repository`` also starts its
    outcome series at 0 (:func:`prime_outcomes`)."""
    for severity, placement in placed:
        FINDINGS.inc(provider=provider or "unknown", severity=severity, placement=placement)
    if repository:
        prime_outcomes(provider, repository)


__all__ = ["FINDINGS", "FINDING_OUTCOMES", "METRICS", "OUTCOMES", "REVIEWS", "TRIGGERS", "count_findings",
           "count_outcome", "count_review", "count_trigger", "prime_outcomes", "repo_key", "reset"]
