from __future__ import annotations

import json
import re
from typing import Any

from ...models import Session, ToolCall
from ..research_source_quality import research_source_is_credible

_URL_PATTERN = re.compile(r"https?://[^\s)>]+", re.IGNORECASE)
_GREETING_ONLY_PATTERNS = (
    re.compile(r"^\s*(hello|hi|hey)\b", re.IGNORECASE),
    re.compile(r"\b(how can i help|what would you like me to do)\b", re.IGNORECASE),
)
_TRANSITION_ONLY_PATTERNS = (
    re.compile(r"^\s*(i am now|i will now|i'll now|next i will|let me)\b", re.IGNORECASE),
    re.compile(r"\b(come back with findings|gathering evidence now)\b", re.IGNORECASE),
)
_RUNTIME_ERROR_PATTERNS = (
    re.compile(r"all configured runtime targets failed", re.IGNORECASE),
    re.compile(r"agent stopped because", re.IGNORECASE),
    re.compile(r"selected runtime kept producing transition text", re.IGNORECASE),
)
_OPERATIONS_EVIDENCE_TOOL_NAMES = {
    "aws_read_operation",
    "get_k8s_deployments",
    "get_k8s_events",
    "get_pod_logs",
    "list_failed_pods",
    "query_loki",
    "query_prometheus",
}


def determine_sub_agent_evidence_profile(parent_session: Session | None) -> str:
    """The child-acceptance profile from the parent's explicit state: workflow, routing intent, agent type.

    Nothing derived from the prompt is an input.
    """
    if parent_session is None:
        return "generic"
    metadata = dict(parent_session.metadata_ or {})
    routing_intent = str(metadata.get("routing_intent") or "").strip().lower()
    if routing_intent == "documentation":
        return "documentation"
    agent_type = str(parent_session.agent_type or "").strip().lower()
    if routing_intent in {"operations", "sre"} or agent_type in {"operations", "sre"}:
        return "operations"
    return "generic"


def _dedupe_tool_names(tool_calls: list[ToolCall], *, include_all: bool) -> list[str]:
    seen: set[str] = set()
    tool_names: list[str] = []
    for call in tool_calls:
        tool_name = str(call.tool_name or "").strip()
        if not tool_name:
            continue
        if not include_all and str(call.status or "").strip().lower() != "success":
            continue
        if tool_name in seen:
            continue
        seen.add(tool_name)
        tool_names.append(tool_name)
    return tool_names


def _extract_source_urls(final_response: str) -> list[str]:
    seen: set[str] = set()
    source_urls: list[str] = []
    for match in _URL_PATTERN.findall(str(final_response or "").strip()):
        candidate = match.rstrip(".,);]")
        if candidate in seen:
            continue
        seen.add(candidate)
        source_urls.append(candidate)
    return source_urls


def _extract_source_urls_from_tool_calls(tool_calls: list[ToolCall]) -> list[str]:
    seen: set[str] = set()
    source_urls: list[str] = []

    def remember(candidate: str) -> None:
        normalized = str(candidate or "").strip().rstrip(".,);]")
        if not normalized or normalized in seen:
            return
        seen.add(normalized)
        source_urls.append(normalized)

    for call in tool_calls:
        if str(call.status or "").strip().lower() != "success":
            continue
        tool_name = str(call.tool_name or "").strip()
        payload = _tool_payload(call)
        params = call.parameters if isinstance(call.parameters, dict) else {}
        if tool_name == "web_search":
            for item in list(payload.get("results") or []):
                if not isinstance(item, dict):
                    continue
                remember(str(item.get("url") or ""))
            continue
        if tool_name == "ingest_document_source":
            source = payload.get("source") if isinstance(payload.get("source"), dict) else {}
            remember(str(source.get("url") or payload.get("url") or params.get("url") or ""))
            continue
        if tool_name in {"web_fetch", "browser_open_url"}:
            remember(str(payload.get("url") or params.get("url") or ""))
    return source_urls


def _extract_source_candidates_from_tool_calls(tool_calls: list[ToolCall]) -> list[dict[str, str]]:
    seen: set[str] = set()
    source_candidates: list[dict[str, str]] = []

    def remember(url: str, *, title: str = "", snippet: str = "") -> None:
        normalized = str(url or "").strip().rstrip(".,);]")
        if not normalized or normalized in seen:
            return
        seen.add(normalized)
        candidate = {"url": normalized}
        if str(title or "").strip():
            candidate["title"] = str(title).strip()
        if str(snippet or "").strip():
            candidate["snippet"] = str(snippet).strip()
        source_candidates.append(candidate)

    for call in tool_calls:
        if str(call.status or "").strip().lower() != "success":
            continue
        tool_name = str(call.tool_name or "").strip()
        payload = _tool_payload(call)
        params = call.parameters if isinstance(call.parameters, dict) else {}
        if tool_name == "web_search":
            for item in list(payload.get("results") or []):
                if not isinstance(item, dict):
                    continue
                remember(
                    str(item.get("url") or ""),
                    title=str(item.get("title") or ""),
                    snippet=str(item.get("snippet") or ""),
                )
            continue
        if tool_name == "ingest_document_source":
            source = payload.get("source") if isinstance(payload.get("source"), dict) else {}
            remember(
                str(source.get("url") or payload.get("url") or params.get("url") or ""),
                title=str(source.get("title") or source.get("name") or ""),
                snippet=str(source.get("excerpt") or payload.get("excerpt") or ""),
            )
            continue
        if tool_name in {"web_fetch", "browser_open_url"}:
            remember(
                str(payload.get("url") or params.get("url") or ""),
                title=str(payload.get("title") or ""),
                snippet=str(payload.get("excerpt") or payload.get("summary") or ""),
            )
    return source_candidates


def _tool_payload(call: ToolCall) -> dict[str, Any]:
    payload = call.result
    if isinstance(payload, dict):
        return payload
    if isinstance(payload, str):
        try:
            decoded = json.loads(payload)
        except Exception:
            return {}
        return decoded if isinstance(decoded, dict) else {}
    return {}


def _has_successful_source_evidence(tool_calls: list[ToolCall]) -> bool:
    for call in tool_calls:
        if str(call.status or "").strip().lower() != "success":
            continue
        tool_name = str(call.tool_name or "").strip()
        payload = _tool_payload(call)
        if tool_name == "web_search" and list(payload.get("results") or []):
            return True
        if tool_name == "ingest_document_source":
            source = payload.get("source") if isinstance(payload.get("source"), dict) else {}
            if source or str(payload.get("url") or "").strip():
                return True
        if tool_name in {"web_fetch", "browser_open_url"} and str(payload.get("url") or "").strip():
            return True
        if tool_name == "search_confluence":
            if list(payload.get("results") or []) or int(payload.get("total") or 0) > 0:
                return True
        if tool_name == "knowledge_search" and list(payload.get("evidence") or []):
            return True
        if tool_name in {"get_confluence_page", "knowledge_read"} and payload:
            return True
    return False


def _has_successful_operations_evidence(tool_calls: list[ToolCall]) -> bool:
    for call in tool_calls:
        if str(call.status or "").strip().lower() != "success":
            continue
        tool_name = str(call.tool_name or "").strip().lower()
        if not tool_name:
            continue
        if tool_name in _OPERATIONS_EVIDENCE_TOOL_NAMES:
            return True
        if tool_name.startswith(("aws_", "get_aws_", "list_aws_", "search_aws_", "query_aws_")):
            return True
        if "_aws_" in tool_name:
            return True
    return False


def _classify_response_kind(final_response: str) -> str:
    text = str(final_response or "").strip()
    if not text:
        return "empty"
    if any(pattern.search(text) for pattern in _RUNTIME_ERROR_PATTERNS):
        return "runtime_error"
    if len(text) <= 280 and any(pattern.search(text) for pattern in _GREETING_ONLY_PATTERNS):
        return "greeting_only"
    if len(text) <= 320 and any(pattern.search(text) for pattern in _TRANSITION_ONLY_PATTERNS):
        return "transition_only"
    return "substantive"


def summarize_sub_agent_evidence_quality(
    *,
    profile: str,
    topic: str,
    status: str,
    final_response: str,
    tool_calls: list[ToolCall],
) -> dict[str, Any]:
    normalized_status = str(status or "").strip().lower()
    successful_tool_names = _dedupe_tool_names(tool_calls, include_all=False)
    response_kind = _classify_response_kind(final_response)
    source_urls = list(
        dict.fromkeys(
            [
                * _extract_source_urls(final_response),
                * _extract_source_urls_from_tool_calls(tool_calls),
            ]
        )
    )
    source_candidates = _extract_source_candidates_from_tool_calls(tool_calls)
    credible_source_candidates = [
        candidate
        for candidate in source_candidates
        if research_source_is_credible(
            topic=topic,
            title=str(candidate.get("title") or candidate.get("url") or ""),
            url=str(candidate.get("url") or ""),
            snippet=str(candidate.get("snippet") or ""),
        )
    ]
    source_grounded = bool(source_urls) or _has_successful_source_evidence(tool_calls)
    operations_grounded = _has_successful_operations_evidence(tool_calls)

    rejection_reasons: list[str] = []
    if normalized_status != "completed":
        rejection_reasons.append("session_not_completed")
    if not successful_tool_names:
        rejection_reasons.append("no_successful_tool_calls")
    if not str(final_response or "").strip():
        rejection_reasons.append("missing_final_response")
    elif response_kind != "substantive":
        rejection_reasons.append(f"{response_kind}_response")
    if profile == "operations" and not operations_grounded:
        rejection_reasons.append("missing_operations_evidence_tools")
    return {
        "profile": profile,
        "accepted": not rejection_reasons,
        "response_kind": response_kind,
        "rejection_reasons": rejection_reasons,
        "has_tool_evidence": bool(successful_tool_names),
        "is_source_grounded": source_grounded,
        "is_operations_grounded": operations_grounded,
        "successful_tool_names": successful_tool_names,
        "successful_tool_call_count": sum(
            1 for call in tool_calls if str(call.status or "").strip().lower() == "success"
        ),
        "source_urls": source_urls,
        "source_candidates": source_candidates,
        "credible_source_candidates": credible_source_candidates,
        "credible_source_count": len(credible_source_candidates),
        "source_url_count": len(source_urls),
    }


def build_sub_agent_evidence_record(
    *,
    profile: str,
    topic: str,
    session: Session,
    task: str,
    final_response: str,
    tool_calls: list[ToolCall],
    include_tool_names: bool,
    title: str | None,
    message_count: int,
) -> dict[str, Any]:
    quality = summarize_sub_agent_evidence_quality(
        profile=profile,
        topic=topic,
        status=str(session.status or ""),
        final_response=final_response,
        tool_calls=tool_calls,
    )
    return {
        "session_id": session.id,
        "status": session.status,
        "title": title,
        "task": task,
        "final_response": final_response,
        "message_count": message_count,
        "tool_call_count": len(tool_calls),
        "tool_names": _dedupe_tool_names(tool_calls, include_all=True) if include_tool_names else [],
        "started_at": session.started_at.isoformat() if session.started_at else None,
        "ended_at": session.ended_at.isoformat() if session.ended_at else None,
        "quality": quality,
    }


def extract_sub_agent_evidence_counts(payload: Any) -> tuple[int | None, int | None]:
    if not isinstance(payload, dict):
        return None, None
    accepted_count = payload.get("accepted_count")
    rejected_count = payload.get("rejected_count")
    if accepted_count is None and isinstance(payload.get("accepted_subthreads"), list):
        accepted_count = len(payload["accepted_subthreads"])
    if accepted_count is None and isinstance(payload.get("subthreads"), list):
        accepted_count = len(payload["subthreads"])
    if rejected_count is None and isinstance(payload.get("rejected_subthreads"), list):
        rejected_count = len(payload["rejected_subthreads"])
    accepted = int(accepted_count) if isinstance(accepted_count, int | float) else None
    rejected = int(rejected_count) if isinstance(rejected_count, int | float) else None
    return accepted, rejected
