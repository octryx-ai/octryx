"""Prometheus text for the bounded rate-limit key state. Aggregate only: no key, address, credential or request detail
reaches a metric."""

from __future__ import annotations

from ..rate_limit_state_policy import EVICTION_REASONS, state_snapshots


def render_rate_limit_state_metrics() -> list[str]:
    snapshots = state_snapshots()
    lines = [
        "# HELP octryx_rate_limit_tracked_keys Client keys currently retained per rate limiter store",
        "# TYPE octryx_rate_limit_tracked_keys gauge",
    ]
    for snapshot in snapshots:
        lines.append(f'octryx_rate_limit_tracked_keys{{store="{snapshot.name}"}} {snapshot.current_keys}')
    lines.extend(
        [
            "# HELP octryx_rate_limit_key_capacity Configured hard bound on retained keys per store",
            "# TYPE octryx_rate_limit_key_capacity gauge",
        ]
    )
    for snapshot in snapshots:
        lines.append(f'octryx_rate_limit_key_capacity{{store="{snapshot.name}"}} {snapshot.capacity}')
    lines.extend(
        [
            "# HELP octryx_rate_limit_key_evictions_total Rate limiter key evictions by store and reason",
            "# TYPE octryx_rate_limit_key_evictions_total counter",
        ]
    )
    for snapshot in snapshots:
        for reason in EVICTION_REASONS:
            lines.append(
                "octryx_rate_limit_key_evictions_total"
                f'{{store="{snapshot.name}",reason="{reason}"}} {snapshot.evictions.get(reason, 0)}'
            )
    return lines


__all__ = ["render_rate_limit_state_metrics"]
