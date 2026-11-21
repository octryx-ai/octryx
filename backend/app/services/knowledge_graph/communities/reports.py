"""LLM community report prompt and its JSON answer."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from app.services.prompt_catalog import render_prompt

GenerateFn = Callable[[str], Awaitable[str]]

# The JSON report ``_parse_report`` reads: fixed protocol, fills ``{answer_contract}``.
REPORT_ANSWER_CONTRACT = 'Return strict JSON: {"title": str, "summary": str}.'


def build_report_prompt(members: list[Any], edges: list[Any]) -> str:
    member_ids = {node.id for node in members}
    name_by_id = {node.id: node.display_name for node in members}
    entity_lines = "\n".join(
        f"- {node.display_name} ({node.node_type}): {node.description or ''}".rstrip() for node in members[:40]
    )
    relation_lines = "\n".join(
        f"- {name_by_id[edge.source_node_id]} —{edge.edge_type}→ {name_by_id[edge.target_node_id]}"
        for edge in edges
        if edge.source_node_id in member_ids and edge.target_node_id in member_ids
    )[:4000]
    return render_prompt(
        "knowledge.graph.community_report",
        answer_contract=REPORT_ANSWER_CONTRACT,
        entity_lines=entity_lines,
        relation_lines=relation_lines,
    )


def _parse_report(raw: str) -> tuple[str, str] | None:
    import json
    import re

    text = str(raw or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text).strip()
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(data, dict):
        return None
    title = str(data.get("title") or "").strip()
    summary = str(data.get("summary") or "").strip()
    if not summary:
        return None
    return (title or summary[:80], summary)
