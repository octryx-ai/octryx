"""Listing-limit helpers for the Confluence tools."""

from typing import Any

from ..services.request_analysis import effective_limit_from_request_analysis
from .context import ToolContext


def effective_confluence_list_limit(
    requested_limit: Any,
    context: ToolContext,
    *,
    root_page_id: str | None = None,
    default_limit: int = 1000,
    force_requested_limit: bool = False,
) -> int:
    if force_requested_limit and requested_limit not in (None, ""):
        try:
            return max(1, min(int(requested_limit), 1000))
        except (TypeError, ValueError):
            return default_limit
    return effective_limit_from_request_analysis(
        snapshot=context.turn_context_snapshot,
        fallback_user_message=context.current_user_message,
        requested_limit=requested_limit,
        default_if_unspecified=default_limit,
        hard_max=1000,
    )
