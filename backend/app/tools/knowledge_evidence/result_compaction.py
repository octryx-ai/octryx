"""Knowledge-owned, bounded model evidence; originals remain in tool artifacts."""

from __future__ import annotations

from typing import Any

from ...services.content_security.knowledge_fence import NOTICE_FIELD, shorten_fenced
from ...services.tool_result_compression.support import _estimate_tokens

MAX_PASSAGES = 8
MAX_PASSAGE_CHARS = 1200
MODEL_TOKEN_BUDGET = 6000
# The citation identity survives compaction: the openable ``source_url``, its ready ``cite_as`` link and the
# exact revision, next to the locator.
PASSAGE_FIELDS = (
    "workspace", "evidence_key", "citation", "source_title", "source_url", "cite_as",
    "revision_id", "revision", "span_ordinal", "kind", "pages", "lines", "section",
    "line_start", "line_end", "page_start", "page_end",
)


def compact_knowledge_search(result: dict[str, Any]) -> dict[str, Any]:
    if result.get("state") != "ok":
        return dict(result)
    evidence = []
    for passage in (result.get("evidence") or [])[:MAX_PASSAGES]:
        if not isinstance(passage, dict):
            continue
        item = {key: passage[key] for key in PASSAGE_FIELDS if key in passage}
        # The text arrives fenced (``knowledge_fence``): the cut keeps the end marker.
        item["text"], item["text_truncated"] = shorten_fenced(passage.get("text"), MAX_PASSAGE_CHARS)
        evidence.append(item)
    facts = result.get("facts") or {}
    compact = {
        "state": result.get("state"),
        "workspace_id": result.get("workspace_id"),
        "result_count": result.get("result_count"),
        "mode_states": result.get("mode_states"),
        "evidence": evidence,
        "omitted_passages": max(0, len(result.get("evidence") or []) - len(evidence)),
        "facts": dict(facts),
        "_compact_result_token_budget": MODEL_TOKEN_BUDGET,
    }
    if "changes" in result:
        compact["changes"] = result["changes"]
    if NOTICE_FIELD in result:
        compact[NOTICE_FIELD] = result[NOTICE_FIELD]
    # Preserve a usable cited passage instead of falling through to a key-only preview.
    while _estimate_tokens(compact) > MODEL_TOKEN_BUDGET and len(evidence) > 1:
        evidence.pop()
        compact["omitted_passages"] += 1
    return compact


def register_result_compactors() -> None:
    from ...agent.engine.messages._tool_compaction_registry import register_tool_result_compactor

    register_tool_result_compactor("knowledge_search", compact_knowledge_search)
