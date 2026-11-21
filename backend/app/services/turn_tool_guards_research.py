"""Technical source credibility guard for research turns.

Service-owned module (same family as ``turn_tool_guards_aws``): a research or delegated-evidence
documentation turn on a technical topic may only fetch sources the research policy deems credible.
"""

from __future__ import annotations

from typing import Any

from .prompt_catalog import render_prompt
from .research_source_quality import research_url_is_credible, topic_requires_technical_sources
from .turn_tool_guards import _active_guard_rule, _guard_result

_DELEGATED_EVIDENCE_STEP_MARKERS = ("delegated evidence", "sub-task")


def technical_source_guard_result(
    *,
    tool_name: str,
    tool_args: dict[str, Any],
    context_snapshot: dict[str, Any] | None,
    exec_policy_config: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    guard_rule = _active_guard_rule(exec_policy_config, "technical_source_credibility_required")
    if guard_rule is None:
        return None
    normalized_tool_name = str(tool_name or "").strip().lower()
    if normalized_tool_name not in {"ingest_document_source", "web_fetch", "browser_open_url"}:
        return None

    snapshot = context_snapshot or {}
    request_analysis = snapshot.get("request_analysis") if isinstance(snapshot.get("request_analysis"), dict) else {}
    workflow_contract = (
        request_analysis.get("workflow_contract")
        if isinstance(request_analysis.get("workflow_contract"), dict)
        else {}
    )
    workflow_id = str(workflow_contract.get("workflow_id") or "").strip().lower()
    topic = _resolve_technical_research_topic(snapshot=snapshot, request_analysis=request_analysis)
    if not topic or not topic_requires_technical_sources(topic):
        return None
    if workflow_id:
        return None

    url = str(tool_args.get("url") or tool_args.get("source_url") or "").strip()
    if not url or not url.lower().startswith(("http://", "https://")):
        return None
    if research_url_is_credible(topic=topic, url=url):
        return None

    return _guard_result({
        "error": render_prompt("tool_guard.technical_source.error", tool_name=tool_name, topic=topic, url=url),
        "guardrail": "technical_source_credibility_required",
        "blocked_url": url,
        "topic": topic,
        "suggested_next_tools": ["web_search", "codesearch"],
        "reason": render_prompt("tool_guard.technical_source.reason"),
    }, guard_rule)


def _resolve_technical_research_topic(*, snapshot: dict[str, Any], request_analysis: dict[str, Any]) -> str:
    agent = snapshot.get("agent") if isinstance(snapshot.get("agent"), dict) else {}
    if str(agent.get("type") or "").strip().lower() != "documentation":
        return ""

    current_step = snapshot.get("current_step") if isinstance(snapshot.get("current_step"), dict) else {}
    step_name = str(current_step.get("name") or "").strip().lower()
    if not any(marker in step_name for marker in _DELEGATED_EVIDENCE_STEP_MARKERS):
        return ""

    for key in ("canonical_message", "source_user_message"):
        candidate = str(request_analysis.get(key) or "").strip()
        if candidate:
            return candidate

    for message in reversed(snapshot.get("recent_history") or []):
        if not isinstance(message, dict):
            continue
        if str(message.get("role") or "").strip().lower() != "user":
            continue
        candidate = str(message.get("content") or "").strip()
        if candidate:
            return candidate
    return ""


__all__ = ["technical_source_guard_result"]
