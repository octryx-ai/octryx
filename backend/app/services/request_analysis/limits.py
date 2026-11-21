from __future__ import annotations

from typing import Any

from app.services.request_analysis.patterns import GENERIC_READ_LIMIT_KEYS, IMPLICIT_LIMIT_PARAM_KEYS, LIMIT_PATTERN


def extract_explicit_limit(user_message: str) -> int | None:
    """The limit the user literally states ("top 5", "10 tickets"), a request parameter."""
    match = LIMIT_PATTERN.search(str(user_message or "").strip())
    if not match:
        return None
    raw_value = match.group("value") or match.group("count")
    if not raw_value:
        return None
    try:
        return int(raw_value)
    except ValueError:
        return None


def request_analysis_from_snapshot(snapshot: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(snapshot, dict):
        return {}
    analysis = snapshot.get("request_analysis")
    if isinstance(analysis, dict):
        return analysis
    return {}


def user_explicitly_requested_limit_from_snapshot(snapshot: dict[str, Any] | None) -> bool:
    analysis = request_analysis_from_snapshot(snapshot)
    return bool(analysis.get("explicit_limit_requested"))


def sanitize_implicit_limit_params(
    *,
    tool_name: str,
    params: dict[str, Any] | None,
    snapshot: dict[str, Any] | None,
    fallback_user_message: str | None = None,
) -> dict[str, Any]:
    cleaned = dict(params or {})
    if not cleaned:
        return cleaned
    analysis = request_analysis_from_snapshot(snapshot)
    explicit_requested = bool(analysis.get("explicit_limit_requested"))
    if not analysis and fallback_user_message:
        explicit_requested = extract_explicit_limit(fallback_user_message) is not None
    if explicit_requested:
        return cleaned
    for key in IMPLICIT_LIMIT_PARAM_KEYS.get(str(tool_name or "").strip(), ()):
        cleaned.pop(key, None)
    normalized_tool_name = str(tool_name or "").strip().lower()
    if normalized_tool_name.startswith(("list_", "search_", "query_", "get_", "read_")) or normalized_tool_name in {
        "nrql_query",
    }:
        for key in GENERIC_READ_LIMIT_KEYS:
            cleaned.pop(key, None)
    return cleaned


def effective_limit_from_request_analysis(
    *,
    snapshot: dict[str, Any] | None,
    fallback_user_message: str | None = None,
    requested_limit: Any,
    default_if_unspecified: int,
    hard_max: int,
    minimum: int = 1,
) -> int:
    analysis = request_analysis_from_snapshot(snapshot)
    if not analysis and fallback_user_message:
        analysis = {
            "explicit_limit_requested": extract_explicit_limit(fallback_user_message) is not None,
            "explicit_limit_value": extract_explicit_limit(fallback_user_message),
        }
    explicit_requested = bool(analysis.get("explicit_limit_requested"))
    raw_limit = (
        requested_limit
        if explicit_requested and requested_limit is not None
        else analysis.get("explicit_limit_value")
        if explicit_requested
        else None
    )
    try:
        limit = int(raw_limit or default_if_unspecified)
    except (TypeError, ValueError):
        limit = default_if_unspecified
    return max(minimum, min(limit, hard_max))
