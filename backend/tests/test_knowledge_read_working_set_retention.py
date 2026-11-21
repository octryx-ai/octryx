"""Successful Knowledge reads keep their exact text in the within-turn working set (research evidence binding).

Live shape (S3.2, Haiku without thinking keeps three recent results detailed): two searches, three parallel reads
and the brief submission. Recency alone turned the first read into a snapshot without text, and the governed
research phase then held with ``current_read_pair_missing``. Reads are now retained like repository sources, newest
distinct key first and within the research evidence bounds; non-read results keep the recency policy.
"""
from __future__ import annotations

from app.services.tool_artifact import (
    build_tool_artifact_envelope,
    build_within_turn_working_set_messages,
    parse_tool_artifact_envelope,
    serialize_tool_artifact_envelope,
)
from app.services.tool_artifact.working_set import MAX_RETAINED_KNOWLEDGE_READS, MAX_RETAINED_KNOWLEDGE_TOTAL_CHARS


def _read(key, text):
    return "knowledge_read", {"state": "ok", "workspace": "Test", "evidence_key": key, "text": text}


def _search(query):
    return "knowledge_search", {"state": "ok", "query": query, "items": [{"title": "x" * 300}] * 4}


def _history(groups):
    messages = [{"role": "system", "content": "system"}, {"role": "user", "content": "Research first_word."}]
    for g, group in enumerate(groups):
        calls = [(f"call-{g}-{n}", name, payload) for n, (name, payload) in enumerate(group)]
        messages.append({"role": "assistant", "content": "", "tool_calls": [
            {"id": ident, "type": "function", "function": {"name": name, "arguments": "{}"}}
            for ident, name, _ in calls]})
        for ident, name, payload in calls:
            messages.append({"role": "tool", "tool_call_id": ident, "content": serialize_tool_artifact_envelope(
                build_tool_artifact_envelope(artifact_id=ident, tool_name=name, payload=payload, include_result=True))})
    return messages


def _shown(messages):
    return {envelope["result"]["evidence_key"]: envelope["result"]["text"]
            for envelope in (parse_tool_artifact_envelope(m["content"]) for m in messages if m.get("role") == "tool")
            if envelope.get("tool_name") == "knowledge_read" and "result" in envelope}


def _detailed_tools(messages):
    return [envelope["tool_name"] for envelope in
            (parse_tool_artifact_envelope(m["content"]) for m in messages if m.get("role") == "tool")
            if "result" in envelope]


def test_live_shape_keeps_every_read_after_the_submission():
    reads = [_read("k:2", "Overview " * 40), _read("k:5", "How to use " * 40), _read("k:4", "Why " * 40)]
    messages = _history([[_search("first_word"), _search("first_word whitespace")], reads,
                         [("submit_research_brief", {"state": "recorded", "summary": "s" * 2000})]])
    built, stats = build_within_turn_working_set_messages(messages, token_budget=900000, thinking_level="off")
    assert _shown(built) == {"k:2": reads[0][1]["text"], "k:5": reads[1][1]["text"], "k:4": reads[2][1]["text"]}
    # The recency policy still applies to everything else: the two searches lose their bodies.
    assert _detailed_tools(built).count("knowledge_search") == 0
    assert stats["detailed_tool_messages"] == 4


def test_repeated_key_keeps_only_the_newest_read_and_bounds_hold():
    first, again = _read("k:1", "old " * 20), _read("k:1", "new " * 20)
    many = [_read(f"m:{n}", "y" * 3000) for n in range(MAX_RETAINED_KNOWLEDGE_READS + 3)]
    messages = _history([[first], *[[item] for item in many], [again], [_search("later")], [_search("later2")]])
    built, _ = build_within_turn_working_set_messages(messages, token_budget=900000, thinking_level="off")
    shown = _shown(built)
    assert shown.get("k:1") == again[1]["text"]
    assert len(shown) <= MAX_RETAINED_KNOWLEDGE_READS
    assert sum(len(text) for key, text in shown.items() if key.startswith("m:")) <= MAX_RETAINED_KNOWLEDGE_TOTAL_CHARS


def test_failed_or_empty_reads_keep_the_recency_policy():
    failed = ("knowledge_read", {"state": "forbidden", "evidence_key": "k:9"})
    empty = _read("k:8", "   ")
    messages = _history([[failed], [empty], [_search("a")], [_search("b")], [_search("c")], [_search("d")]])
    built, _ = build_within_turn_working_set_messages(messages, token_budget=900000, thinking_level="off")
    assert "knowledge_read" not in _detailed_tools(built)
