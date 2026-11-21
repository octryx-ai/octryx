"""The loop's execution-contract message, rendered from explicit sources only.

The message is injected only when an explicit requirement exists (``analysis_first``): the
context plan's coverage domains (a scenario profile's ``enforce_domain_coverage``), several
context domains or a ``summary_aggregation`` route.
Nothing in it is derived from the prompt's wording except the language contract.
"""

from __future__ import annotations

from typing import Any

from app.services.prompt_catalog import render_prompt


def build_request_analysis_contract_message(request_analysis: dict[str, Any]) -> str:
    required_domains = request_analysis.get("required_domains") or request_analysis.get("requested_domains") or []
    domains_text = ", ".join(str(item) for item in required_domains) if required_domains else "none"
    limit_policy = str(request_analysis.get("default_limit_policy") or "unbounded_unless_user_specified")
    language_contract = request_analysis.get("language_contract") or {}
    source_language = str(language_contract.get("source_language") or "en").strip() or "en"
    canonical_language = str(language_contract.get("canonical_language") or "en").strip() or "en"
    output_language = str(language_contract.get("output_language") or "en").strip() or "en"
    return render_prompt(
        "analysis.execution_contract",
        source_language=source_language,
        canonical_language=canonical_language,
        output_language=output_language,
        domains_text=domains_text,
        limit_policy=limit_policy,
    )
