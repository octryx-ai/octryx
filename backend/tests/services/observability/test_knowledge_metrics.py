"""Knowledge first, measured: knowledge and web lookups by outcome, phase, workflow, engine and Workspace."""

from __future__ import annotations

import json
import uuid
from datetime import timedelta
from types import SimpleNamespace

import pytest

from app.models import ToolCall, UsageEvent
from app.services.observability import agent_metrics, attribution
from app.services.observability.knowledge_metrics import ERROR, HIT, MISS, phase_usage, query_outcome
from app.time_utils import utc_now
from tests.observability_support import admin_user, session_for, workspace

PREFIX = "mcp__octryx-knowledge__"


@pytest.fixture(autouse=True)
def _empty_metrics():
    agent_metrics.reset()
    yield
    agent_metrics.reset()


def _result(payload: dict | str) -> dict:
    return {"is_error": False, "excerpt": payload if isinstance(payload, str) else json.dumps(payload)}


@pytest.mark.parametrize(("tool", "status", "result", "outcome"), [
    ("knowledge_search", "success", _result({"state": "ok", "result_count": 2}), HIT),
    ("knowledge_search", "success", _result({"state": "ok", "result_count": 0}), MISS),
    ("knowledge_search", "success", _result({"state": "unavailable"}), ERROR),
    ("knowledge_search", "error", _result({"state": "ok", "result_count": 2}), ERROR),
    ("web_search", "success", _result({"state": "ok", "results": [{"url": "u"}], "count": 1}), HIT),
    ("web_search", "success", _result({"state": "ok", "results": [], "count": 0}), MISS),
    ("web_search", "success", _result({"state": "unavailable", "reason": "transport"}), ERROR),
    ("web_fetch", "success", _result({"url": "https://coffee.example", "content": "x"}), HIT),
    ("web_fetch", "success", _result(""), MISS),
    ("web_fetch", "success", _result({"state": "denied", "reason": "source_blocked"}), MISS),
    ("web_fetch", "success", _result({"error": "Fetch failed: Client error '404 Not Found' for url 'x'"}), MISS),
    ("web_fetch", "success", _result({"error": "Fetch failed: Server error '503 Service Unavailable'"}), ERROR),
    ("web_fetch", "success", _result({"error": "Fetch failed: All connection attempts failed"}), ERROR),
    ("web_fetch", "success", {"is_error": True, "excerpt": "boom"}, ERROR),
])
def test_each_lookup_has_one_outcome(tool, status, result, outcome):
    assert query_outcome(tool, status, result) == outcome


def _value(text: str, line_start: str) -> float:
    found = [line for line in text.splitlines() if line.startswith(line_start + " ")]
    assert len(found) == 1, (line_start, [line for line in text.splitlines() if "knowledge_queries" in line])
    return float(found[0].rsplit(" ", 1)[1])


@pytest.mark.asyncio
async def test_lookups_are_counted_with_the_run_context_engine_and_workspace_name(db):
    admin = await admin_user(db)
    project = await workspace(db, "Coffee")
    session = await session_for(db, admin, project=project)
    # The session's model calls run on the Claude seat: its lookups count under that engine.
    db.add(UsageEvent(id=str(uuid.uuid4()), session_id=session.id, user_id=admin.id, provider="anthropic_seat",
                      model="claude-x", tokens_in=1, tokens_out=1))
    await db.commit()
    with attribution.scope(run="run-1", workflow="spec-writing", phase="research", workspace=project.id):
        db.add(ToolCall(session_id=session.id, tool_name=PREFIX + "knowledge_search", status="success",
                        result=_result({"state": "ok", "result_count": 3})))
        db.add(ToolCall(session_id=session.id, tool_name=PREFIX + "web_search", status="success",
                        result=_result({"state": "ok", "results": [], "count": 0})))
        db.add(ToolCall(session_id=session.id, tool_name="WebFetch", status="requested"))  # the engine's own tool
        db.add(ToolCall(session_id=session.id, tool_name="read_file", status="success"))  # not a lookup
        await db.commit()
    # Outside a run: phase and workflow are "none", the engine of a session without model calls is governed.
    chat = await session_for(db, admin, project=project)
    db.add(ToolCall(session_id=chat.id, tool_name=PREFIX + "knowledge_search", status="success",
                    result=_result({"state": "ok", "result_count": 0})))
    await db.commit()

    text = "\n".join(agent_metrics.render())
    name = "octryx_knowledge_queries_total"
    run = 'phase="research",workflow="spec-writing",engine="claude_code",workspace="Coffee"'
    assert _value(text, f'{name}{{tool="knowledge_search",outcome="hit",{run}}}') == 1
    assert _value(text, f'{name}{{tool="web_search",outcome="miss",{run}}}') == 1
    assert _value(text, f'{name}{{tool="web_fetch_native",outcome="unknown",{run}}}') == 1
    none = 'phase="none",workflow="none",engine="governed",workspace="Coffee"'  # the chat session's Workspace
    assert _value(text, f'{name}{{tool="knowledge_search",outcome="miss",{none}}}') == 1
    assert 'tool="read_file",outcome' not in text


def test_a_phase_reports_its_lookups_since_it_was_entered():
    now = utc_now()

    def row(tool: str, payload: dict, minutes: int = 0) -> SimpleNamespace:
        return SimpleNamespace(tool_name=PREFIX + tool, status="success", result=_result(payload),
                               created_at=now + timedelta(minutes=minutes))

    rows = [row("knowledge_search", {"state": "ok", "result_count": 1}, minutes=-10),  # an earlier phase
            row("knowledge_search", {"state": "ok", "result_count": 1}),
            row("knowledge_search", {"state": "ok", "result_count": 0}),
            row("web_search", {"state": "ok", "results": [{"url": "u"}], "count": 1}),
            row("web_fetch", {"error": "Fetch failed: All connection attempts failed"}),
            SimpleNamespace(tool_name="WebSearch", status="requested", result=None, created_at=now),
            SimpleNamespace(tool_name="Bash", status="success", result={}, created_at=now)]
    assert phase_usage(rows, now - timedelta(minutes=1)) == {
        "knowledge_hits": 1, "knowledge_misses": 1, "knowledge_errors": 0, "web_calls": 3, "web_hits": 1}
