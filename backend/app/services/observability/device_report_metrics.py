"""Counters of what devices report besides their turns (``octryx_device_change_*``, ``octryx_device_mcp_*``): the
changes a Stop reported without a patch or after a retry, and the launcher's removed MCP authentication marks.
They are rendered with the workflow metrics (``workflow_metrics.METRICS``).
"""

from __future__ import annotations

from .metric_types import Counter

DEVICE_CHANGE_UNAVAILABLE = Counter(
    "octryx_device_change_unavailable_total", "Device changes reported without a patch, by the step that failed "
    "(cat-file, read-tree, add, diff, no_base, other_base, unknown)", ("step",))
DEVICE_CHANGE_RETRIED = Counter(
    "octryx_device_change_retried_total", "Device changes whose git steps were tried again, by outcome (recovered: "
    "the second attempt gave the patch; failed: it did not)", ("outcome",))
DEVICE_MCP_AUTH_CLEARED = Counter(
    "octryx_device_mcp_auth_cache_cleared_total", "Device sessions whose launcher removed Claude Code's \"needs "
    "authentication\" mark for the platform's MCP server before the session (a mark hides the platform tools for "
    "~15 minutes), by profile", ("profile",))

_CHANGE_STEPS = ("cat-file", "read-tree", "add", "diff")


def device_change_reported(change: dict) -> None:
    """A Stop's change as the run keeps it (``octryx/facts``), counted when it is recorded (so a
    repeat after the retry is seen, not guessed)."""
    attempts = change.get("attempts")
    unavailable = bool(change.get("base_unavailable"))
    if isinstance(attempts, int) and attempts > 1:
        DEVICE_CHANGE_RETRIED.inc(outcome="failed" if unavailable else "recovered")
    if not unavailable:
        return
    reason = str(change.get("reason") or "")
    step = next((name for name in _CHANGE_STEPS if reason.startswith(name)), "")
    if not step:
        step = ("no_base" if reason.startswith("no base") else "other_base" if reason.startswith("the device diffed")
                else "unknown")
    DEVICE_CHANGE_UNAVAILABLE.inc(step=step)


def mcp_auth_cache_cleared(profile: str) -> None:
    """A device session's launcher removed the platform server's "needs authentication" mark (one
    broken turn's mark would cost the following turns their platform tools), counted at the session's registration."""
    DEVICE_MCP_AUTH_CLEARED.inc(profile=profile)
