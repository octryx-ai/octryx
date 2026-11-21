"""The structured rolling summary: parsing the model's answer, a heuristic fallback, rendering and references."""

from __future__ import annotations

import json
import re
from json import JSONDecodeError

from ._summarizer_evidence import (
    parse_reference_markers,
    strip_reference_markers,
    validate_reference_markers,
)


def render_messages(messages: list) -> str:
    lines = []
    for m in messages:
        role = m.role.upper()
        content = (m.content or "").strip()
        # Skip tool noise – keep only meaningful text
        if m.role == "assistant" and m.tool_calls and not content:
            tool_names = [tc.get("function", {}).get("name", "?") for tc in (m.tool_calls or [])]
            content = f"[called tools: {', '.join(tool_names)}]"
        if content:
            lines.append(f"{role}: {content[:500]}")
    return "\n".join(lines)


def clean_summary_text(value: str | None, *, limit: int = 280) -> str:
    text = " ".join(str(value or "").strip().split())
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."


def _extract_entities_from_text(text: str) -> list[str]:
    entities = re.findall(r"\b[A-Z][A-Z0-9]+-\d+\b|\b[a-z0-9_-]+(?:service|deployment|pod|branch)\b", text or "")
    deduped: list[str] = []
    seen: set[str] = set()
    for item in entities:
        key = item.lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped[:6]


def parse_existing_summary_json(existing_summary: str | None, metadata: dict | None = None) -> dict:
    if metadata and isinstance(metadata.get("summary_json"), dict):
        return dict(metadata["summary_json"])
    if not existing_summary:
        return {}
    try:
        payload = json.loads(existing_summary)
        if isinstance(payload, dict):
            return payload
    except (JSONDecodeError, TypeError):
        return {}
    return {}


def _extract_tool_name(message: object) -> str:
    tool_calls = getattr(message, "tool_calls", None)
    if not tool_calls:
        return ""
    try:
        return str(tool_calls[0].get("function", {}).get("name") or "")
    except (AttributeError, IndexError, KeyError, TypeError):
        return ""


def _normalize_structured_summary(payload: dict | None, *, fallback_goal: str = "") -> dict:
    raw = payload or {}
    findings_raw = raw.get("findings") if isinstance(raw.get("findings"), list) else []
    findings: list[dict] = []
    for item in findings_raw[:12]:
        if isinstance(item, dict):
            text = clean_summary_text(item.get("text") or item.get("summary") or "")
            if not text:
                continue
            entities = (
                item.get("entities") if isinstance(item.get("entities"), list) else _extract_entities_from_text(text)
            )
            findings.append(
                {
                    "type": clean_summary_text(item.get("type") or "fact", limit=40),
                    "text": text,
                    "entities": [str(entity) for entity in entities[:6]],
                }
            )
        else:
            text = clean_summary_text(str(item))
            if text:
                findings.append({"type": "fact", "text": text, "entities": _extract_entities_from_text(text)})
    actions_raw = raw.get("actions_taken") if isinstance(raw.get("actions_taken"), list) else []
    actions: list[dict] = []
    for item in actions_raw[:12]:
        if isinstance(item, dict):
            tool = clean_summary_text(item.get("tool") or "", limit=60)
            action = clean_summary_text(item.get("action") or item.get("step") or "", limit=120)
            result = clean_summary_text(item.get("result") or item.get("outcome") or "", limit=180)
            if tool or action or result:
                actions.append({"tool": tool, "action": action, "result": result})
        else:
            text = clean_summary_text(str(item), limit=180)
            if text:
                actions.append({"tool": "", "action": text, "result": ""})
    open_items_raw = raw.get("open_items") if isinstance(raw.get("open_items"), list) else []
    open_items = [
        clean_summary_text(item, limit=180) for item in open_items_raw if clean_summary_text(item, limit=180)
    ][:10]
    state = str(raw.get("state") or "unknown").strip().lower()
    if state not in {"in_progress", "blocked", "completed", "unknown"}:
        state = "unknown"
    goal = clean_summary_text(raw.get("goal") or fallback_goal, limit=220)
    return {
        "goal": goal,
        "findings": findings,
        "actions_taken": actions,
        "open_items": open_items,
        "state": state,
    }


def _heuristic_structured_summary(existing_summary_json: dict, new_messages: list) -> dict:
    goal = clean_summary_text(existing_summary_json.get("goal") if isinstance(existing_summary_json, dict) else "")
    findings = list(existing_summary_json.get("findings") or []) if isinstance(existing_summary_json, dict) else []
    actions = list(existing_summary_json.get("actions_taken") or []) if isinstance(existing_summary_json, dict) else []
    open_items = list(existing_summary_json.get("open_items") or []) if isinstance(existing_summary_json, dict) else []
    state = (
        str(existing_summary_json.get("state") or "unknown") if isinstance(existing_summary_json, dict) else "unknown"
    )

    for message in new_messages:
        content = clean_summary_text(getattr(message, "content", "") or "", limit=240)
        if not content:
            continue
        lowered = content.lower()
        if not goal and getattr(message, "role", "") == "user":
            goal = content
        if any(
            token in lowered for token in ("root cause", "oomkilled", "crashloopbackoff", "error", "failed", "timeout")
        ):
            findings.append({"type": "finding", "text": content, "entities": _extract_entities_from_text(content)})
        elif any(
            token in lowered for token in ("updated", "created", "commented", "changed", "applied", "called tools")
        ):
            tool_name = _extract_tool_name(message)
            actions.append({"tool": tool_name, "action": content, "result": ""})
        if "human_input_required" in lowered or content.endswith("?"):
            open_items.append(content)
            state = "blocked"
    if findings and state == "unknown":
        state = "in_progress"
    return _normalize_structured_summary(
        {
            "goal": goal,
            "findings": findings,
            "actions_taken": actions,
            "open_items": open_items,
            "state": state,
        },
        fallback_goal=goal,
    )


def render_structured_summary(summary_json: dict | None) -> str:
    summary = _normalize_structured_summary(summary_json or {})
    parts: list[str] = []
    if summary.get("goal"):
        parts.append(f"Goal: {summary['goal']}")
    findings = summary.get("findings") or []
    if findings:
        parts.append("Findings:")
        parts.extend(f"- [{item.get('type')}] {item.get('text')}" for item in findings[:8])
    actions = summary.get("actions_taken") or []
    if actions:
        parts.append("Actions taken:")
        for item in actions[:8]:
            tool = str(item.get("tool") or "").strip()
            action = str(item.get("action") or "").strip()
            result = str(item.get("result") or "").strip()
            line = " - ".join(part for part in [tool, action, result] if part)
            parts.append(f"- {line}")
    open_items = summary.get("open_items") or []
    if open_items:
        parts.append("Open items:")
        parts.extend(f"- {item}" for item in open_items[:6])
    parts.append(f"State: {summary.get('state') or 'unknown'}")
    return "\n".join(parts).strip()


def parse_summary_response(
    response_text: str,
    *,
    fallback_goal: str,
    existing_summary_json: dict,
    new_messages: list,
) -> dict:
    text = str(response_text or "").strip()
    payload: dict | None = None
    if text:
        try:
            parsed = json.loads(text)
            if isinstance(parsed, dict):
                payload = parsed
        except (JSONDecodeError, TypeError):
            payload = None
    if payload is None:
        payload = _heuristic_structured_summary(existing_summary_json, new_messages)
    return _normalize_structured_summary(payload, fallback_goal=fallback_goal)


def apply_reference_markers(structured_summary: dict, evidence_refs: list[dict]) -> tuple[dict, list[str]]:
    """Validate reference markers in a summary against collected evidence.

    Returns the summary with hallucinated markers stripped from its text fields
    plus the list of validated reference ids (in order of first appearance).
    """
    serialized = json.dumps(structured_summary, ensure_ascii=True)
    markers = parse_reference_markers(serialized)
    if not markers:
        return structured_summary, []
    validated = validate_reference_markers(markers, evidence_refs)
    if len(validated) == len(markers):
        return structured_summary, validated
    valid_set = set(validated)
    cleaned = dict(structured_summary)
    cleaned["goal"] = strip_reference_markers(cleaned.get("goal") or "", valid_set)
    cleaned["findings"] = [
        {**item, "text": strip_reference_markers(item.get("text") or "", valid_set)}
        for item in (cleaned.get("findings") or [])
        if isinstance(item, dict)
    ]
    cleaned["actions_taken"] = [
        {
            **item,
            "action": strip_reference_markers(item.get("action") or "", valid_set),
            "result": strip_reference_markers(item.get("result") or "", valid_set),
        }
        for item in (cleaned.get("actions_taken") or [])
        if isinstance(item, dict)
    ]
    cleaned["open_items"] = [
        strip_reference_markers(item, valid_set) for item in (cleaned.get("open_items") or [])
    ]
    return cleaned, validated
