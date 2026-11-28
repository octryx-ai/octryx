"""Runtime web and code search tools over the platform's governed web search."""

from __future__ import annotations

from typing import Any

from app.tools.context import ToolContext

from ...services.web_search.service import (
    MODE_TRUSTED_ONLY,
    SearchOutcome,
    governed_search,
    workspace_search_mode,
)
from ._runtime_cli_search_filters import normalize_domain_token, search_result_allowed
from ._runtime_web_evidence import with_hit_sources

MAX_DOMAIN_FILTERS = 20
STATE_MESSAGES = {
    "invalid_request": "The search query was empty or too long.",
    "needs_configuration": "Web search is not configured for this workspace (no search provider, no data "
    "classification, or no trusted sources for a trusted-only workspace).",
    "denied": "This workspace's data classification does not allow sending search queries to the provider.",
    "unavailable": "Web search is temporarily unavailable.",
}


def _domains(raw: object) -> list[str]:
    values = raw if isinstance(raw, list) else []
    return [domain for domain in (normalize_domain_token(str(item)) for item in values[:MAX_DOMAIN_FILTERS]) if domain]


def _project_id(context: ToolContext) -> str | None:
    project_id = str((context.project_config or {}).get("project_id") or "").strip()
    return project_id if project_id and project_id in (context.project_ids or []) else None


def _answer(outcome: SearchOutcome, *, query: str, mode: str) -> dict[str, Any]:
    # Each hit names its source (source_title, source_url, cite_as), the shape of a Knowledge passage.
    body = with_hit_sources(outcome.to_dict())
    body.update({"query": query, "source": outcome.provider, "workspace_search_mode": mode})
    if not outcome.ok:
        body["error"] = STATE_MESSAGES.get(outcome.state, STATE_MESSAGES["unavailable"])
    return body


async def _search(params: dict[str, Any], context: ToolContext, *, code: bool) -> dict[str, Any]:
    query = str(params.get("query") or "").strip()
    if not query:
        return {"error": "query is required", "state": "invalid_request"}
    if not context.db:
        return {"error": STATE_MESSAGES["unavailable"], "state": "unavailable"}
    project_id = _project_id(context)
    mode = await workspace_search_mode(context.db, project_id)
    outcome = await governed_search(
        context.db,
        project_id=project_id,
        query=query,
        num_results=int(params.get("num_results") or 8),
        trusted_only=mode == MODE_TRUSTED_ONLY,
        restrict_to=_domains(params.get("include_domains")),
        exclude=_domains(params.get("exclude_domains")),
        code=code,
        session_id=str(context.session_id or "") or None,
    )
    exclude_terms = [str(item).strip().lower() for item in (params.get("exclude_terms") or []) if str(item).strip()]
    if outcome.ok and (exclude_terms or params.get("exclude_preprints")):
        outcome.hits = [
            hit
            for hit in outcome.hits
            if search_result_allowed(
                hit.to_dict(),
                include_domains=[],
                exclude_domains=[],
                exclude_terms=exclude_terms[:MAX_DOMAIN_FILTERS],
                exclude_preprints=bool(params.get("exclude_preprints")),
            )
        ]
    return _answer(outcome, query=query, mode=mode)


class WebSearchTool:
    name = "web_search"
    description = (
        "Search the web through the platform's governed search provider. Results pass the platform "
        "blocklist and the workspace's trusted-source registry. Returns titles, URLs, and snippets; every "
        "result carries source_url and a cite_as markdown link to cite it by."
    )

    async def execute(self, params: dict[str, Any], context: ToolContext) -> dict[str, Any]:
        return await _search(params, context, code=False)


class CodeSearchTool:
    name = "codesearch"
    description = (
        "Search for code, APIs, and technical documentation through the platform's governed search "
        "provider (code-optimised where the provider supports it)."
    )

    async def execute(self, params: dict[str, Any], context: ToolContext) -> dict[str, Any]:
        return await _search(params, context, code=True)


__all__ = ["CodeSearchTool", "WebSearchTool"]
