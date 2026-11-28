"""``citations_present`` for a run-bound octryx-claude phase: the observed answer against the platform's sources."""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ....models import Message, ToolCall
from ...agent_gateway.capability import PLATFORM_MCP_TOOL_PREFIX
from ...answer_evidence.check import check_answer_evidence
from ...answer_evidence.evidence import collect_turn_evidence

OBSERVED_ANSWER_PREFIX = "gw:a:"
_SOURCE_URL = re.compile(r'"source_url"\s*:\s*"([^"\s]{1,2048})"')
_CITE_AS = re.compile(r'"cite_as"\s*:\s*"((?:[^"\\]|\\.){1,600})"')


def _decoded(value: str) -> str:
    try:
        return str(json.loads(f'"{value}"'))
    except ValueError:
        return value


def _result_tree(excerpt: str) -> dict[str, Any]:
    try:
        parsed = json.loads(excerpt)
    except ValueError:
        # The recorded excerpt is bounded and may cut the JSON: its source fields still count.
        items: list[dict[str, Any]] = [{"source_url": url} for url in _SOURCE_URL.findall(excerpt)]
        items += [{"cite_as": _decoded(label)} for label in _CITE_AS.findall(excerpt)]
        return {"items": items, "text": excerpt}
    return parsed if isinstance(parsed, dict) else {"items": parsed}


def platform_sources(rows: Sequence[ToolCall], *, since: datetime | None) -> list[dict[str, Any]]:
    history = []
    for row in rows:
        if since is not None and (row.created_at is None or row.created_at < since):
            continue
        result = row.result if isinstance(row.result, dict) else {}
        if (str(row.tool_name or "").startswith(PLATFORM_MCP_TOOL_PREFIX) and row.status == "success"
                and result.get("is_error") is False):
            history.append({"result": _result_tree(str(result.get("excerpt") or ""))})
    return history


async def observed_answer(db: AsyncSession, session_id: str, *, since: datetime | None) -> str:
    query = select(Message.content).where(
        Message.session_id == session_id, Message.role == "assistant",
        Message.idempotency_key.like(f"{OBSERVED_ANSWER_PREFIX}%"))
    if since is not None:
        query = query.where(Message.created_at >= since)
    newest = (await db.execute(query.order_by(Message.created_at.desc()).limit(1))).scalar_one_or_none()
    return str(newest or "")


async def citation_counts(db: AsyncSession, session_id: str, rows: Sequence[ToolCall], *,
                          since: datetime | None) -> tuple[int, int]:
    evidence = collect_turn_evidence(platform_sources(rows, since=since))
    check = check_answer_evidence(await observed_answer(db, session_id, since=since), evidence)
    return check.cited_count, check.evidence_url_count


__all__ = ["citation_counts", "observed_answer", "platform_sources"]
