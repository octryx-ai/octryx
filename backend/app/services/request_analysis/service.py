from __future__ import annotations

from typing import Any

from .limits import extract_explicit_limit

# The platform does not detect or translate the user's language; the model answers in it (no
# language-specific branches). The execution contract states that instead of a language code.
LANGUAGE_CONTRACT = {
    "source_language": "as written by the user",
    "canonical_language": "as written by the user",
    "output_language": "the language of the user's message",
}


def build_request_analysis(
    user_message: str,
    *,
    route_reason: str = "",
    required_domains: list[str] | set[str] | tuple[str, ...] | None = None,
    context_domains: list[str] | set[str] | tuple[str, ...] | None = None,
    enforce_domain_coverage: bool = False,
) -> dict[str, Any]:
    """Describe the turn's explicit requirements for the loop's execution contract.

    No field decides intent from the prompt. The domains are the context plan's
    (``context_domains``) and its explicit coverage domains (``required_domains`` with
    ``enforce_domain_coverage``, a scenario profile's setting); the prompt adds none.

    The prompt is read only for a literally stated limit ("top 5"), a request parameter.
    """
    analysis_message = str(user_message or "").strip()
    route_domains = {str(item).strip().lower() for item in (context_domains or []) if str(item).strip()}
    required = {str(item).strip().lower() for item in (required_domains or []) if str(item).strip()}
    all_domains = sorted(route_domains | required)
    explicit_limit_value = extract_explicit_limit(analysis_message)
    return {
        "route_reason": str(route_reason or "").strip(),
        "language_contract": dict(LANGUAGE_CONTRACT),
        "source_message": str(user_message or "").strip(),
        "canonical_message": analysis_message,
        "requested_domains": all_domains,
        "required_domains": sorted(required),
        "enforce_domain_coverage": bool(enforce_domain_coverage),
        "explicit_limit_requested": explicit_limit_value is not None,
        "explicit_limit_value": explicit_limit_value,
        "default_limit_policy": "unbounded_unless_user_specified",
        "execution_phases": ["analyze_request", "execute_tools", "finalize_response"],
        "analysis_first": bool(
            route_reason == "summary_aggregation" or enforce_domain_coverage or len(all_domains) >= 2
        ),
    }


def required_summary_tools_from_request_analysis(request_analysis: dict[str, Any] | None) -> set[str]:
    """The summary tools of the explicit coverage domains (a scenario profile's coverage setting)."""
    from ..system_config.tool_domains import DEFAULT_AGENT_TOOL_DOMAIN_CONFIG

    if not isinstance(request_analysis, dict) or not request_analysis.get("enforce_domain_coverage"):
        return set()
    tools: set[str] = set()
    for domain in request_analysis.get("required_domains") or []:
        tools.update(
            DEFAULT_AGENT_TOOL_DOMAIN_CONFIG["summary_domain_tool_allowlists"].get(
                str(domain).strip().lower(),
                [],
            )
        )
    return tools


__all__ = [
    "build_request_analysis",
    "required_summary_tools_from_request_analysis",
]
