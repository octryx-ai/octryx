"""Source reference extraction and matching for Engineering Knowledge lifecycle changes."""

from __future__ import annotations

from typing import Any

from sqlalchemy import String, cast, or_

from ...models import ConnectorWatcherEvent, EngineeringKnowledgeGraphNode
from .lifecycle_state import MAX_MATCH_REFS


def extract_engineering_knowledge_event_refs(event: ConnectorWatcherEvent) -> list[str]:
    raw = dict(event.raw_payload_json or {})
    normalized = dict(event.normalized_json or {})
    scope = dict(event.scope_json or {})
    refs: list[str] = [
        event.external_id or "",
        raw.get("key") or "",
        raw.get("canonical_source") or "",
        normalized.get("external_id") or "",
    ]
    refs.extend(_collect_known_refs(raw))
    refs.extend(_collect_known_refs(normalized))
    refs.extend(_collect_known_refs(scope))
    return _safe_match_refs(refs)


def _collect_known_refs(value: Any) -> list[str]:
    refs: list[str] = []
    if isinstance(value, dict):
        for key, current in value.items():
            lowered = str(key).lower()
            if lowered in {
                "canonical_source",
                "cve",
                "document_key",
                "external_id",
                "id",
                "issue_key",
                "job_name",
                "key",
                "package",
                "package_name",
                "page_id",
                "repository",
                "repository_slug",
                "source",
                "source_ref",
                "url",
            }:
                refs.extend(_collect_string_refs(current))
            elif isinstance(current, dict | list):
                refs.extend(_collect_known_refs(current))
    elif isinstance(value, list):
        for item in value[:20]:
            refs.extend(_collect_known_refs(item))
    return refs


def _collect_string_refs(value: Any) -> list[str]:
    if isinstance(value, dict):
        return _collect_known_refs(value)
    if isinstance(value, list):
        refs: list[str] = []
        for item in value[:20]:
            refs.extend(_collect_string_refs(item))
        return refs
    text = str(value or "").strip()
    return [text] if text else []


def _refs_match_filter(refs: list[str]) -> Any:
    clauses = []
    for ref in refs:
        needle = f"%{ref.lower()}%"
        clauses.append(func_lower_json(EngineeringKnowledgeGraphNode.source_refs_json).like(needle))
        clauses.append(func_lower_json(EngineeringKnowledgeGraphNode.properties_json).like(needle))
        clauses.append(func_lower_json(EngineeringKnowledgeGraphNode.provenance_json).like(needle))
    return or_(*clauses)


def func_lower_json(column: Any) -> Any:
    from sqlalchemy import func

    return func.lower(cast(column, String))


def _safe_match_refs(refs: list[Any]) -> list[str]:
    seen: set[str] = set()
    safe: list[str] = []
    for value in refs:
        text = str(value or "").strip()
        if len(text) < 4:
            continue
        lowered = text.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        safe.append(text[:300])
        if len(safe) >= MAX_MATCH_REFS:
            break
    return safe


def _is_delete_or_sensitive_event(event_type: str) -> bool:
    return any(marker in event_type for marker in ("deleted", "removed", "purged", "sensitive", "revoked"))


def _event_reason(event: ConnectorWatcherEvent, *, target_status: str) -> str:
    event_type = event.event_type or "source event"
    if target_status == "retracted":
        return f"Source event {event_type} requires retraction or deletion cleanup."
    return f"Source event {event_type} changed upstream evidence; fact requires review."
