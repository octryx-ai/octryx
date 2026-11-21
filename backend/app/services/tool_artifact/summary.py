from __future__ import annotations

import json
import re
from typing import Any

_ARTIFACT_KIND = "tool_result"
_DETAIL_HINT = "Older tool results may be compacted. Call `load_tool_artifact` with the artifact_id only when you need more detail."


def _truncate_text(value: str, max_chars: int) -> str:
    text = str(value or "")
    if max_chars <= 0 or len(text) <= max_chars:
        return text
    if max_chars <= 3:
        return text[:max_chars]
    return text[: max_chars - 3].rstrip() + "..."


def _stringify_scalar(value: Any, *, max_chars: int = 120) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, str):
        return _truncate_text(value, max_chars)
    return _truncate_text(json.dumps(value, ensure_ascii=False, default=str), max_chars)


def _top_level_facts(value: Any, *, max_facts: int) -> list[str]:
    facts: list[str] = []
    if not isinstance(value, dict):
        rendered = _stringify_scalar(value, max_chars=140)
        return [rendered] if rendered else []

    priority_keys = [
        "status",
        "count",
        "total",
        "total_count",
        "entry_count",
        "updated_count",
        "created_count",
        "deleted_count",
        "failed_count",
        "summary",
        "title",
        "name",
        "project_name",
        "repository",
        "repo_slug",
        "branch_name",
        "space_key",
        "query",
        "jql",
    ]
    seen: set[str] = set()
    for key in priority_keys:
        if key in value:
            rendered = _stringify_scalar(value.get(key))
            if rendered:
                facts.append(f"{key}={rendered}")
                seen.add(key)
            if len(facts) >= max_facts:
                return facts

    for key, raw in value.items():
        if key in seen:
            continue
        if isinstance(raw, list):
            facts.append(f"{key}={len(raw)} items")
        elif isinstance(raw, dict):
            nested_scalars: list[str] = []
            for nested_key, nested_value in raw.items():
                rendered = _stringify_scalar(nested_value, max_chars=80)
                if rendered:
                    nested_scalars.append(f"{nested_key}={rendered}")
                if len(nested_scalars) >= 2:
                    break
            if nested_scalars:
                facts.append(f"{key}: " + ", ".join(nested_scalars))
        else:
            rendered = _stringify_scalar(raw)
            if rendered:
                facts.append(f"{key}={rendered}")
        if len(facts) >= max_facts:
            break
    return facts


def build_tool_artifact_summary(tool_name: str, payload: Any) -> str:
    normalized_tool_name = str(tool_name or "").strip() or "tool"
    if isinstance(payload, dict) and payload.get("error"):
        return f"{normalized_tool_name} failed: {_truncate_text(str(payload.get('error') or ''), 180)}"
    facts = _top_level_facts(payload, max_facts=3)
    if facts:
        return f"{normalized_tool_name}: " + "; ".join(facts)
    if isinstance(payload, list):
        return f"{normalized_tool_name}: {len(payload)} items returned"
    return f"{normalized_tool_name} completed"


_SHORTENED_HINT = (
    "This result is shortened. Call `load_tool_artifact` with the artifact_id only if the answer needs what is left out."
)
_TAG = re.compile(r"<[^>]+>")
_TEXT_MIN_CHARS = 40
_KEPT_SHARE = 0.9


def _text_and_items(value: Any) -> tuple[int, int]:
    """Characters of the longer texts (markup stripped) and the number of list items, recursively."""
    if isinstance(value, str):
        text = " ".join(_TAG.sub(" ", value).split())
        # Prose only: hashes, ids and URLs are not what a reader of the answer needs.
        return (len(text), 0) if len(text) >= _TEXT_MIN_CHARS and " " in text else (0, 0)
    if isinstance(value, dict):
        parts = [_text_and_items(item) for item in value.values()]
        return sum(p[0] for p in parts), sum(p[1] for p in parts)
    if isinstance(value, (list, tuple)):
        parts = [_text_and_items(item) for item in value]
        return sum(p[0] for p in parts), len(value) + sum(p[1] for p in parts)
    return 0, 0


def result_was_shortened(raw: Any, compact: Any) -> bool:
    """Whether the result the model sees lost text or list items of the tool's real result.

    A ``detail_available`` hint on a result whose compact form kept the whole page text (a 276-character
    Confluence page as ``excerpt``) makes a model call ``load_tool_artifact`` by reflex, one more model call each.
    Only a result that really lost text or items says so.
    """
    raw_text, raw_items = _text_and_items(raw)
    text, items = _text_and_items(compact)
    return text < raw_text * _KEPT_SHARE or items < raw_items * _KEPT_SHARE


def build_tool_artifact_envelope(
    *,
    artifact_id: str,
    tool_name: str,
    payload: Any,
    include_result: bool,
    max_facts: int = 5,
    shortened: bool = True,
) -> dict[str, Any]:
    """A tool result for the model; ``shortened=False`` (the full result is included) carries no load hint."""
    envelope = {
        "_artifact_kind": _ARTIFACT_KIND,
        "artifact_id": str(artifact_id or "").strip(),
        "tool_name": str(tool_name or "").strip(),
        "summary": build_tool_artifact_summary(tool_name, payload),
        "salient_facts": _top_level_facts(payload, max_facts=max_facts),
    }
    if shortened or not include_result:
        envelope["detail_available"] = True
        envelope["detail_hint"] = _SHORTENED_HINT if include_result else _DETAIL_HINT
    if include_result:
        envelope["result"] = payload
    return envelope


def serialize_tool_artifact_envelope(envelope: dict[str, Any]) -> str:
    return json.dumps(envelope, ensure_ascii=False, default=str)


def parse_tool_artifact_envelope(content: Any) -> dict[str, Any] | None:
    if isinstance(content, dict):
        candidate = content
    elif isinstance(content, str):
        try:
            candidate = json.loads(content)
        except json.JSONDecodeError:
            return None
    else:
        return None
    if not isinstance(candidate, dict):
        return None
    if candidate.get("_artifact_kind") != _ARTIFACT_KIND:
        return None
    if not candidate.get("artifact_id") or not candidate.get("tool_name"):
        return None
    return candidate


def _build_snapshot(envelope: dict[str, Any], *, fact_limit: int, minimal: bool = False) -> dict[str, Any]:
    snapshot = {
        "_artifact_kind": _ARTIFACT_KIND,
        "artifact_id": envelope.get("artifact_id"),
        "tool_name": envelope.get("tool_name"),
        "summary": envelope.get("summary"),
        "detail_available": True,
        "detail_hint": _DETAIL_HINT,
    }
    if not minimal:
        facts = list(envelope.get("salient_facts") or [])
        if facts:
            snapshot["salient_facts"] = facts[: max(1, fact_limit)]
    return snapshot
