"""LightRAG-style query keyword extraction (dual-level).

The KEYWORDS role extracts *low-level* keywords (specific entities/names) and
*high-level* keywords (themes/concepts) from the question. Low-level terms drive
entity vector search; high-level terms drive relation vector search. When no
governed runtime is available the extraction degrades deterministically to
tokenization (logged) — retrieval keeps working, just without the semantic split.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Sequence
from dataclasses import dataclass, field

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.prompt_catalog import render_prompt
from app.services.prompt_catalog.out_of_turn import scoped_prompt_set, single_workspace

from ..error_facts import error_type
from .llm_runtime import ROLE_KEYWORDS, KnowledgeLLMUnavailableError, build_generate_fn

logger = logging.getLogger(__name__)

_TOKEN = re.compile(r"[a-zA-Z0-9_-]{3,}")
_STOPWORDS = {
    "the", "and", "for", "with", "who", "what", "when", "where", "which", "how",
    "why", "does", "did", "was", "are", "this", "that", "from", "into", "about",
}


@dataclass(frozen=True)
class QueryKeywords:
    low_level: list[str] = field(default_factory=list)
    high_level: list[str] = field(default_factory=list)
    source: str = "deterministic"

    def low_text(self, fallback: str) -> str:
        return " ".join(self.low_level) or fallback

    def high_text(self, fallback: str) -> str:
        return " ".join(self.high_level) or fallback


def _deterministic_keywords(query: str) -> QueryKeywords:
    tokens = [t for t in _TOKEN.findall(query) if t.lower() not in _STOPWORDS]
    return QueryKeywords(low_level=tokens, high_level=tokens, source="deterministic")


# The JSON answer ``_parse_keywords`` reads: fixed protocol, fills ``{answer_contract}``.
KEYWORDS_ANSWER_CONTRACT = (
    'Return strict JSON: {"low_level": [specific entity names, identifiers, people, '
    'services], "high_level": [themes, concepts, relationship topics]}.'
)


def build_keywords_prompt(query: str) -> str:
    return render_prompt(
        "knowledge.graph.keywords", answer_contract=KEYWORDS_ANSWER_CONTRACT, query=query.strip()[:500]
    )


def _parse_keywords(raw: str, query: str) -> QueryKeywords:
    text = str(raw or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text).strip()
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return _deterministic_keywords(query)
    if not isinstance(data, dict):
        return _deterministic_keywords(query)
    low = [str(item).strip() for item in (data.get("low_level") or []) if str(item).strip()]
    high = [str(item).strip() for item in (data.get("high_level") or []) if str(item).strip()]
    if not low and not high:
        return _deterministic_keywords(query)
    return QueryKeywords(low_level=low[:12], high_level=high[:12], source="llm")


async def extract_query_keywords(
    db: AsyncSession,
    *,
    query: str,
    project_ids: Sequence[str] | None = None,
) -> QueryKeywords:
    # LLM keyword split is an explicit opt-in: a runtime must be tagged
    # 'keywords'. Otherwise the deterministic split applies — a per-query LLM
    # call must never silently consume the default chat runtime.
    #
    # ``project_ids`` is the retrieval scope. Without it the admission boundary
    # has no Workspace to evaluate, so a governed gateway runtime is refused and
    # the deterministic split applies — the same shape as "no tagged runtime".
    try:
        generate = await build_generate_fn(
            db,
            project_ids=project_ids,
            role=ROLE_KEYWORDS,
            max_tokens=300,
            require_role_match=True,
        )
        async with scoped_prompt_set(db, workspace_id=single_workspace(project_ids)):
            keywords_prompt = build_keywords_prompt(query)
        return _parse_keywords(await generate(keywords_prompt), query)
    except KnowledgeLLMUnavailableError as exc:
        # Platform-authored message: admission codes or the typed runtime-failure facts.
        logger.info("Keyword extraction runtime unavailable; deterministic split: %s", exc)
    except Exception as exc:  # noqa: BLE001 - retrieval must not fail on keyword extraction
        logger.warning("Keyword extraction failed; deterministic split: error_type=%s", error_type(exc))
    return _deterministic_keywords(query)
