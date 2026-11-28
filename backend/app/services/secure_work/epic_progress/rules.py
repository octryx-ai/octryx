"""Which lane a child of an Epic is in, derived from its recorded events only (no model, no manual status)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

LANE_DONE = "done"
LANE_IN_REVIEW = "in_review"
LANE_IN_PROGRESS = "in_progress"
LANE_OPEN = "open"
LANES = (LANE_DONE, LANE_IN_REVIEW, LANE_IN_PROGRESS, LANE_OPEN)

CHECKS_FAILED = "failed"
CHECKS_GREEN = "green"
CHECKS_RUNNING = "running"

_DONE_STATES = frozenset({"done", "rejected"})
_REVIEW_STATES = frozenset({"review", "ready_to_merge", "changes_requested", "validation"})
_WORKING_STATES = frozenset({"planning", "plan_review", "development", "blocked"})
_ACTIVE_RUNS = frozenset({"running", "waiting", "paused"})
_BUILD_CHECKS = {"failed": CHECKS_FAILED, "successful": CHECKS_GREEN, "in_progress": CHECKS_RUNNING}
_CI_CHECKS = {"failed": CHECKS_FAILED, "succeeded": CHECKS_GREEN, "running": CHECKS_RUNNING}


@dataclass(frozen=True)
class ChildFacts:
    work_state: str
    run_status: str | None = None
    run_phase: str | None = None
    pr_status: str | None = None
    build_status: str | None = None
    ci_state: str | None = None


@dataclass(frozen=True)
class Lane:
    lane: str
    reason: str
    checks: str | None = None
    needs_you: bool = False

    def to_payload(self) -> dict[str, Any]:
        return {"lane": self.lane, "reason": self.reason, "checks": self.checks, "needs_you": self.needs_you}


def checks_of(facts: ChildFacts) -> str | None:
    # The PR host's own build status is the newer fact; the run's CI record covers a PR the host does not report.
    return _BUILD_CHECKS.get(facts.build_status or "") or _CI_CHECKS.get(facts.ci_state or "")


def child_lane(facts: ChildFacts) -> Lane:
    """The first matching rule wins: done, then in review, then in progress, else open."""
    if facts.work_state in _DONE_STATES:
        return Lane(LANE_DONE, "won't do" if facts.work_state == "rejected" else "done")
    if facts.pr_status == "merged":
        return Lane(LANE_DONE, "merged")
    if facts.pr_status == "open" or facts.work_state in _REVIEW_STATES:
        return Lane(LANE_IN_REVIEW, "pull request open" if facts.pr_status == "open" else facts.work_state,
                    checks=checks_of(facts), needs_you=checks_of(facts) == CHECKS_FAILED)
    if facts.run_status in _ACTIVE_RUNS:
        return Lane(LANE_IN_PROGRESS, facts.run_phase or facts.run_status or "",
                    needs_you=facts.run_status == "paused")
    if facts.work_state in _WORKING_STATES:
        return Lane(LANE_IN_PROGRESS, facts.work_state, needs_you=facts.work_state == "blocked")
    return Lane(LANE_OPEN, facts.work_state)


def rollup(lanes: list[Lane]) -> dict[str, int]:
    counts = {lane: 0 for lane in LANES}
    for lane in lanes:
        counts[lane.lane] += 1
    return {**counts, "total": len(lanes), "needs_you": sum(1 for lane in lanes if lane.needs_you)}
