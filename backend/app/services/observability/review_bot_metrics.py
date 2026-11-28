"""The PR review bot, measured (concept §6: "the real values we measure in the first operation")."""

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
    import hashlib

    return hashlib.sha1(repository.strip().lower().encode()).hexdigest()[:8] if repository else "unknown"


def prime_outcomes(provider: str, repository: str) -> None:
    for severity in ("high", "medium", "low"):
        for outcome in FINDING_OUTCOMES:
            key = OUTCOMES._key({"provider": provider or "unknown", "repo": repo_key(repository),
                                 "severity": severity, "outcome": outcome})
            OUTCOMES.series.setdefault(key, 0)


def count_outcome(provider: str, repository: str, severity: str, outcome: str) -> None:
    if outcome in FINDING_OUTCOMES:
        OUTCOMES.inc(provider=provider or "unknown", repo=repo_key(repository),
                     severity=severity if severity in ("high", "medium", "low") else "unknown", outcome=outcome)


def reset() -> None:
    for metric in METRICS:
        metric.series.clear()


def count_trigger(trigger: str, provider: str, outcome: str, reason: str = "") -> None:
    TRIGGERS.inc(trigger=trigger, provider=provider or "unknown", outcome=outcome, reason=reason or "none")


def count_review(provider: str, verdict: str, result: str) -> None:
    REVIEWS.inc(provider=provider or "unknown", verdict=verdict or "none", result=result)


def count_findings(provider: str, placed: list[tuple[str, str]], repository: str = "") -> None:
    for severity, placement in placed:
        FINDINGS.inc(provider=provider or "unknown", severity=severity, placement=placement)
    if repository:
        prime_outcomes(provider, repository)


__all__ = ["FINDINGS", "FINDING_OUTCOMES", "METRICS", "OUTCOMES", "REVIEWS", "TRIGGERS", "count_findings",
           "count_outcome", "count_review", "count_trigger", "prime_outcomes", "repo_key", "reset"]
