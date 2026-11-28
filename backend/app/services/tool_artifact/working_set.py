from __future__ import annotations

from typing import Any

from app.services.token_estimation import estimate_message_tokens
from app.services.tool_artifact.summary import (
    _build_snapshot,
    parse_tool_artifact_envelope,
    serialize_tool_artifact_envelope,
)

from ..prompt_catalog import render_prompt

# Successful Knowledge reads stay detailed in the working set like repository sources: a governed research
# phase binds its brief to exactly the passages the model was shown, so recency must never strip them. The bounds
# match the research evidence bound (at most 8 current reads, 8000 characters each, 30000 in total).
MAX_RETAINED_KNOWLEDGE_READS = 8
MAX_RETAINED_KNOWLEDGE_READ_CHARS = 8000
MAX_RETAINED_KNOWLEDGE_TOTAL_CHARS = 30000


def _knowledge_read_bodies(tool_positions: list[tuple[int, dict[str, Any]]]) -> set[int]:
    kept: set[int] = set()
    seen: set[str] = set()
    spent = 0
    for index, envelope in reversed(tool_positions):
        if len(kept) >= MAX_RETAINED_KNOWLEDGE_READS:
            break
        result = envelope.get("result")
        if envelope.get("tool_name") != "knowledge_read" or not isinstance(result, dict) or result.get("state") != "ok":
            continue
        key, text = result.get("evidence_key"), result.get("text")
        if not isinstance(key, str) or key in seen or not isinstance(text, str) or not text.strip():
            continue
        seen.add(key)
        if len(text) <= MAX_RETAINED_KNOWLEDGE_READ_CHARS and spent + len(text) <= MAX_RETAINED_KNOWLEDGE_TOTAL_CHARS:
            kept.add(index)
            spent += len(text)
    return kept


def _estimate_messages_tokens(messages: list[dict[str, Any]], *, approx_chars_per_token: int) -> int:
    return estimate_message_tokens(messages, approx_chars_per_token=approx_chars_per_token)


def _recent_detail_limit(*, token_budget: int, thinking_level: str | None) -> int:
    base = {
        "off": 1,
        "light": 2,
        "deep": 4,
    }.get(str(thinking_level or "").strip().lower(), 3)
    if token_budget >= 32000:
        return base + 2
    if token_budget >= 18000:
        return base + 1
    if 0 < token_budget <= 8000:
        return max(1, base - 1)
    return base


def _snapshot_fact_limit(*, thinking_level: str | None) -> int:
    return {
        "off": 1,
        "light": 3,
        "deep": 5,
    }.get(str(thinking_level or "").strip().lower(), 4)


def _build_collapsed_tool_history_summary(
    envelopes: list[dict[str, Any]],
    *,
    removed_tool_names: list[str],
    max_entries: int = 6,
) -> dict[str, str] | None:
    if not envelopes:
        return None
    lines = [render_prompt("tool_guard.working_set.collapsed_header")]
    if removed_tool_names:
        lines.append(
            render_prompt(
                "tool_guard.working_set.collapsed_sequence", sequence=" -> ".join(removed_tool_names[-max_entries:])
            )
        )
    lines.append(render_prompt("tool_guard.working_set.collapsed_note"))
    for envelope in envelopes[-max_entries:]:
        artifact_id = str(envelope.get("artifact_id") or "").strip()
        summary = str(envelope.get("summary") or "").strip()
        facts = list(envelope.get("salient_facts") or [])
        fact_suffix = f" | {'; '.join(facts[:2])}" if facts else ""
        lines.append(f"  - {artifact_id}: {summary}{fact_suffix}")
    lines.append(render_prompt("tool_guard.working_set.collapsed_reload"))
    return {"role": "system", "content": "\n".join(lines)}


def _collapse_old_tool_interactions(
    messages: list[dict[str, Any]],
    *,
    preserve_recent_count: int,
    keep_indices: frozenset[int] = frozenset(),
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    if preserve_recent_count <= 0:
        preserve_recent_count = 1

    assistant_tool_call_ids: dict[int, list[str]] = {}
    tool_messages: list[tuple[int, str, dict[str, Any]]] = []
    for index, message in enumerate(messages):
        if message.get("role") == "assistant":
            tool_calls = list(message.get("tool_calls") or [])
            if tool_calls:
                assistant_tool_call_ids[index] = [
                    str(tool_call.get("id") or "").strip()
                    for tool_call in tool_calls
                    if str(tool_call.get("id") or "").strip()
                ]
        elif message.get("role") == "tool":
            envelope = parse_tool_artifact_envelope(message.get("content"))
            if envelope is None:
                continue
            tool_messages.append((index, str(message.get("tool_call_id") or "").strip(), envelope))

    if len(tool_messages) <= preserve_recent_count:
        return messages, {"collapsed_tool_messages": 0, "collapsed_assistant_tool_messages": 0}

    collapsed = [item for item in tool_messages[:-preserve_recent_count] if item[0] not in keep_indices]
    collapsed_indices = {index for index, _, _ in collapsed}
    collapsed_call_ids = {tool_call_id for _, tool_call_id, _ in collapsed if tool_call_id}

    assistant_indices_to_remove: set[int] = set()
    assistant_tool_call_updates: dict[int, list[dict[str, Any]]] = {}
    for index, tool_call_ids in assistant_tool_call_ids.items():
        if not tool_call_ids:
            continue
        tool_calls = list(messages[index].get("tool_calls") or [])
        remaining_tool_calls = [
            tool_call for tool_call in tool_calls if str(tool_call.get("id") or "").strip() not in collapsed_call_ids
        ]
        if len(remaining_tool_calls) == len(tool_calls):
            continue
        content = str(messages[index].get("content") or "").strip()
        if remaining_tool_calls:
            assistant_tool_call_updates[index] = remaining_tool_calls
            continue
        if content:
            assistant_tool_call_updates[index] = []
        else:
            assistant_indices_to_remove.add(index)

    removed_envelopes = [envelope for _, _, envelope in collapsed]
    removed_tool_names = []
    for envelope in removed_envelopes:
        tool_name = str(envelope.get("tool_name") or "").strip()
        if tool_name:
            removed_tool_names.append(tool_name)
    summary_message = _build_collapsed_tool_history_summary(removed_envelopes, removed_tool_names=removed_tool_names)
    if summary_message is None:
        return messages, {"collapsed_tool_messages": 0, "collapsed_assistant_tool_messages": 0}

    # Before a partially collapsed assistant too, so its kept results stay adjacent to it.
    insert_candidates = collapsed_indices | assistant_indices_to_remove | set(assistant_tool_call_updates)
    insert_at = min(insert_candidates) if insert_candidates else None
    if insert_at is None:
        return messages, {"collapsed_tool_messages": 0, "collapsed_assistant_tool_messages": 0}

    rebuilt: list[dict[str, Any]] = []
    inserted = False
    for index, message in enumerate(messages):
        if index == insert_at and not inserted:
            rebuilt.append(summary_message)
            inserted = True
        if index in collapsed_indices or index in assistant_indices_to_remove:
            continue
        if index in assistant_tool_call_updates:
            updated_message = dict(message)
            remaining_tool_calls = assistant_tool_call_updates[index]
            if remaining_tool_calls:
                updated_message["tool_calls"] = remaining_tool_calls
            else:
                updated_message.pop("tool_calls", None)
            rebuilt.append(updated_message)
            continue
        rebuilt.append(message)
    if not inserted:
        rebuilt.append(summary_message)

    return rebuilt, {
        "collapsed_tool_messages": len(collapsed_indices),
        "collapsed_assistant_tool_messages": len(assistant_indices_to_remove),
    }


def build_within_turn_working_set_messages(
    messages: list[dict[str, Any]],
    *,
    token_budget: int,
    thinking_level: str | None,
    approx_chars_per_token: int = 4,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    cloned = [dict(message) for message in messages]
    tool_positions: list[tuple[int, dict[str, Any]]] = []
    for index, message in enumerate(cloned):
        if message.get("role") != "tool":
            continue
        envelope = parse_tool_artifact_envelope(message.get("content"))
        if envelope is None:
            continue
        tool_positions.append((index, envelope))

    if not tool_positions:
        return cloned, {
            "tool_messages_total": 0,
            "detailed_tool_messages": 0,
            "snapshot_tool_messages": 0,
            "minimal_snapshot_tool_messages": 0,
            "estimated_prompt_tokens": _estimate_messages_tokens(cloned, approx_chars_per_token=approx_chars_per_token),
        }

    detail_limit = min(
        len(tool_positions),
        _recent_detail_limit(token_budget=token_budget, thinking_level=thinking_level),
    )
    fact_limit = _snapshot_fact_limit(thinking_level=thinking_level)
    recent_positions = {index for index, _ in tool_positions[-detail_limit:]}
    knowledge = _knowledge_read_bodies(tool_positions)
    detailed_positions = recent_positions | knowledge
    retained = knowledge

    def demotion_order(indices: list[int]) -> list[int]:
        return sorted(indices, key=lambda index: (index in retained, index))
    envelopes = dict(tool_positions)
    snapshot_count = 0

    for index, envelope in tool_positions:
        if index in detailed_positions:
            continue
        cloned[index]["content"] = serialize_tool_artifact_envelope(
            _build_snapshot(envelope, fact_limit=fact_limit)
        )
        snapshot_count += 1

    if token_budget > 0:
        detailed_candidates = demotion_order(sorted(detailed_positions))
        while (
            detailed_candidates
            and _estimate_messages_tokens(cloned, approx_chars_per_token=approx_chars_per_token) > token_budget
        ):
            index = detailed_candidates.pop(0)
            cloned[index]["content"] = serialize_tool_artifact_envelope(
                _build_snapshot(envelopes[index], fact_limit=max(1, fact_limit - 1))
            )
            snapshot_count += 1
            detailed_positions.discard(index)

        minimal_snapshot_count = 0
        older_snapshots = demotion_order([index for index, _ in tool_positions if index not in detailed_positions])
        while (
            older_snapshots
            and _estimate_messages_tokens(cloned, approx_chars_per_token=approx_chars_per_token) > token_budget
        ):
            index = older_snapshots.pop(0)
            cloned[index]["content"] = serialize_tool_artifact_envelope(
                _build_snapshot(envelopes[index], fact_limit=0, minimal=True)
            )
            minimal_snapshot_count += 1
    else:
        minimal_snapshot_count = 0

    collapsed, collapse_stats = _collapse_old_tool_interactions(
        cloned,
        preserve_recent_count=max(2, len(detailed_positions & recent_positions)),
        keep_indices=frozenset(retained),
    )
    cloned = collapsed

    return cloned, {
        "tool_messages_total": len(tool_positions),
        "detailed_tool_messages": len(detailed_positions),
        "snapshot_tool_messages": snapshot_count,
        "minimal_snapshot_tool_messages": minimal_snapshot_count,
        "collapsed_tool_messages": int(collapse_stats.get("collapsed_tool_messages") or 0),
        "collapsed_assistant_tool_messages": int(collapse_stats.get("collapsed_assistant_tool_messages") or 0),
        "estimated_prompt_tokens": _estimate_messages_tokens(cloned, approx_chars_per_token=approx_chars_per_token),
    }


def build_turn_working_summary_message(
    messages: list[dict[str, Any]],
    *,
    thinking_level: str | None,
    max_entries: int | None = None,
) -> dict[str, str] | None:
    tool_envelopes: list[dict[str, Any]] = []
    tool_sequence: list[str] = []
    for message in messages:
        if message.get("role") == "assistant":
            for tool_call in list(message.get("tool_calls") or []):
                function = tool_call.get("function") or {}
                tool_name = str(function.get("name") or "").strip()
                if tool_name:
                    tool_sequence.append(tool_name)
        elif message.get("role") == "tool":
            envelope = parse_tool_artifact_envelope(message.get("content"))
            if envelope is not None:
                tool_envelopes.append(envelope)

    if len(tool_envelopes) < 3:
        return None

    entry_limit = max_entries or {
        "off": 3,
        "light": 4,
        "deep": 6,
    }.get(str(thinking_level or "").strip().lower(), 5)

    recent = tool_envelopes[-entry_limit:]
    lines = [render_prompt("tool_guard.working_set.turn_header")]
    if tool_sequence:
        sequence = " -> ".join(tool_sequence[-max(3, entry_limit) :])
        lines.append(render_prompt("tool_guard.working_set.turn_sequence", sequence=sequence))
    lines.append(render_prompt("tool_guard.working_set.turn_artifacts"))
    for envelope in recent:
        artifact_id = str(envelope.get("artifact_id") or "").strip()
        summary = str(envelope.get("summary") or "").strip()
        facts = list(envelope.get("salient_facts") or [])
        fact_text = f" | {'; '.join(facts[:2])}" if facts else ""
        lines.append(f"  - {artifact_id}: {summary}{fact_text}")
    lines.append(render_prompt("tool_guard.working_set.turn_reload"))
    return {"role": "system", "content": "\n".join(lines)}
