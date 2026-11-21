"""The survey-coverage slide of the AWS deck planner.

How complete the collection itself was, stated the way the AWS diagram
legends state it: every service that was read only partially, skipped or
failed is a bullet and an explicit marker, never a silent omission.
"""

from __future__ import annotations

from typing import Any

from .aws_deck_evidence import (
    Bullet,
    SlideDraft,
    check_number,
    int_or_none,
    join_list,
    missing_source,
    string_list,
)
from .aws_deck_slides import BULLET_SHAPES


def _warning_count(summary: dict[str, Any], aws_snapshot: dict[str, Any]) -> int | None:
    warning_count = int_or_none(summary.get("warning_count"))
    if warning_count is None:
        warnings = aws_snapshot.get("warnings")
        warning_count = len(warnings) if isinstance(warnings, (list, tuple)) else None
    return warning_count


def _add_read_services(draft: SlideDraft, succeeded: list[str], empty: list[str]) -> None:
    if succeeded:
        draft.bullets.append(
            Bullet(
                f"{len(succeeded)} services read completely: {join_list(succeeded)}",
                "service_summary.services_succeeded",
            )
        )
    if empty:
        draft.bullets.append(
            Bullet(
                f"Checked, no resources: {join_list(empty)}",
                "service_summary.services_checked_no_resources",
            )
        )


def _add_service_gaps(
    draft: SlideDraft, partial: list[str], skipped: list[str], failed: list[str]
) -> None:
    if partial:
        draft.bullets.append(
            Bullet(
                f"Read only partially: {join_list(partial)}",
                "service_summary.services_partial",
            )
        )
        for service in partial:
            draft.markers.append(
                check_number(f"Service '{service}' read only partially (service_summary.services_partial)")
            )
    if skipped:
        draft.bullets.append(
            Bullet(
                f"Not read: {join_list(skipped)}",
                "service_summary.services_skipped",
            )
        )
        for service in skipped:
            draft.markers.append(
                missing_source(f"Service '{service}' was not read (service_summary.services_skipped)")
            )
    if failed:
        draft.bullets.append(
            Bullet(f"Failed: {join_list(failed)}", "service_summary.services_failed")
        )
        for service in failed:
            draft.markers.append(
                missing_source(f"Service '{service}' could not be read (service_summary.services_failed)")
            )


def coverage_draft(summary: dict[str, Any], aws_snapshot: dict[str, Any]) -> SlideDraft:
    """How complete the collection itself was — the diagram-legend principle."""
    draft = SlideDraft(
        title="Survey coverage",
        source="service_summary (services_*, warning_count)",
        shape_preference=BULLET_SHAPES,
    )
    succeeded = string_list(summary.get("services_succeeded"))
    failed = string_list(summary.get("services_failed"))
    skipped = string_list(summary.get("services_skipped"))
    partial = string_list(summary.get("services_partial"))
    empty = string_list(summary.get("services_checked_no_resources"))
    warning_count = _warning_count(summary, aws_snapshot)

    _add_read_services(draft, succeeded, empty)
    _add_service_gaps(draft, partial, skipped, failed)
    if warning_count:
        draft.bullets.append(
            Bullet(f"{warning_count} warning(s) in the snapshot", "service_summary.warning_count")
        )
        draft.markers.append(
            check_number(f"Review {warning_count} snapshot warning(s) before approval (warnings)")
        )
    if not draft.bullets:
        draft.markers.append(missing_source("coverage fields (services_*) in the aws_topology_snapshot"))
    return draft


__all__ = ["coverage_draft"]
