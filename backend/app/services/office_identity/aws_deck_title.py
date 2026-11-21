"""The title slide of the AWS deck: account, regions and the evidence date."""

from __future__ import annotations

from typing import Any

from .aws_deck_evidence import (
    Bullet,
    SlideDraft,
    decision,
    join_list,
    missing_source,
    string_list,
    text,
)

#: Layout shapes to try for the title slide, in order (capacity decides, never names).
TITLE_SHAPES = ("title_slide", "title_and_subtitle", "section")

DECK_TITLE_FALLBACK = "AWS architecture"


def title_draft(aws_snapshot: dict[str, Any], scope: dict[str, Any]) -> SlideDraft:
    account_id = text(aws_snapshot.get("account_id"))
    regions = string_list(scope.get("regions")) or [text(aws_snapshot.get("region"))]
    regions = [region for region in regions if region]
    generated_at = text(aws_snapshot.get("generated_at"))

    if account_id:
        title = f"{DECK_TITLE_FALLBACK} — account {account_id}"
        source = "account_id"
    else:
        title = DECK_TITLE_FALLBACK
        source = "account_id (missing)"

    draft = SlideDraft(
        title=title,
        source=source,
        shape_preference=TITLE_SHAPES,
        subtitle=f"Regions: {join_list(regions)}" if regions else "",
        keep_when_empty=True,
    )
    # The evidence date is its own, separately sourced line. Where it lands —
    # a strapline slot of the title layout, or the subtitle line — is decided
    # against the template in ``aws_deck_layout_fit.place_title_date``. Only
    # the day is shown; the full timestamp stays in the source.
    if generated_at:
        day = generated_at.split("T", 1)[0]
        draft.bullets.append(Bullet(f"As of: {day}", f"generated_at ({generated_at})", key="as_of"))
    if not account_id:
        draft.markers.append(missing_source("account_id in the aws_topology_snapshot"))
    if not regions:
        draft.markers.append(missing_source("scope.regions / region in the aws_topology_snapshot"))
    if not generated_at:
        draft.markers.append(missing_source("generated_at in the aws_topology_snapshot"))
    draft.markers.append(
        decision("Confirm deck title and audience — derived from account_id/region, not given")
    )
    return draft


__all__ = ["DECK_TITLE_FALLBACK", "TITLE_SHAPES", "title_draft"]
