"""Tests for summary evidence references and the drill-back tool."""

from app.agent.core.runtime._summarizer_evidence import (
    collect_evidence_from_messages,
    parse_reference_markers,
    render_evidence_prompt_block,
    validate_reference_markers,
)
from app.agent.core.runtime.summarizer import build_history_messages
from app.agent.core.runtime.summary_structure import apply_reference_markers
from app.services.context_compaction import MAX_EVIDENCE_REFS


class _Msg:
    def __init__(self, msg_id="", role="user", content="", tool_calls=None, tool_results=None):
        self.id = msg_id
        self.role = role
        self.content = content
        self.tool_calls = tool_calls
        self.tool_results = tool_results


# ── build_history_messages ───────────────────────────────────────────────────


def _history(count=12):
    return [_Msg(f"m-{idx}", "user", f"message {idx}") for idx in range(count)]


# ── Evidence collection ──────────────────────────────────────────────────────


def test_collect_evidence_shapes_and_excerpt_limit():
    messages = [
        _Msg("m-1", "user", "Investigate payment-service OOMKilled " + "x" * 300),
        _Msg(
            "m-2",
            "assistant",
            "",
            tool_calls=[{"id": "tc-1", "function": {"name": "get_pod_logs", "arguments": "{}"}}],
            tool_results=[{"tool_call_id": "tc-1", "tool_name": "get_pod_logs"}],
        ),
    ]

    refs = collect_evidence_from_messages(messages)

    assert [ref["ref"] for ref in refs] == ["msg:m-1", "tool_call:tc-1"]
    for ref in refs:
        assert set(ref) == {"ref", "role", "tool_name", "excerpt"}
        assert len(ref["excerpt"]) <= 120
    assert refs[1]["tool_name"] == "get_pod_logs"


def test_collect_evidence_caps_at_max_refs():
    messages = [_Msg(f"m-{idx}", "user", f"message {idx}") for idx in range(60)]

    refs = collect_evidence_from_messages(messages)

    assert len(refs) == MAX_EVIDENCE_REFS


def test_collect_evidence_skips_messages_without_ids_or_content():
    refs = collect_evidence_from_messages([_Msg("", "user", "no id"), _Msg("m-1", "assistant", "")])
    assert refs == []


def test_render_evidence_prompt_block_lists_ids():
    block = render_evidence_prompt_block([{"ref": "msg:m-1", "role": "user", "tool_name": "", "excerpt": "hello"}])
    assert "[msg:m-1]" in block
    assert "never invent reference ids" in block
    assert render_evidence_prompt_block([]) == ""


# ── Marker parsing / validation ──────────────────────────────────────────────


def test_marker_parsing_drops_hallucinated_ids():
    evidence = [{"ref": "msg:m-1", "role": "user", "tool_name": "", "excerpt": "hi"}]
    markers = parse_reference_markers("finding [msg:m-1] and fake [msg:bogus] and [tool_call:nope]")
    assert markers == ["msg:m-1", "msg:bogus", "tool_call:nope"]
    assert validate_reference_markers(markers, evidence) == ["msg:m-1"]


def test_apply_reference_markers_strips_invalid_from_summary_text():
    evidence = [{"ref": "msg:m-1", "role": "user", "tool_name": "", "excerpt": "hi"}]
    summary = {
        "goal": "Fix crash [msg:bogus]",
        "findings": [{"type": "fact", "text": "OOMKilled confirmed [msg:m-1] [msg:fake]", "entities": []}],
        "actions_taken": [{"tool": "kubectl", "action": "read logs [tool_call:fake]", "result": ""}],
        "open_items": ["update limits [msg:other]"],
        "state": "in_progress",
    }

    cleaned, validated = apply_reference_markers(summary, evidence)

    assert validated == ["msg:m-1"]
    assert cleaned["goal"] == "Fix crash"
    assert cleaned["findings"][0]["text"] == "OOMKilled confirmed [msg:m-1]"
    assert cleaned["actions_taken"][0]["action"] == "read logs"
    assert cleaned["open_items"] == ["update limits"]


def test_apply_reference_markers_no_markers_is_noop():
    summary = {"goal": "g", "findings": [], "actions_taken": [], "open_items": [], "state": "unknown"}
    cleaned, validated = apply_reference_markers(summary, [])
    assert cleaned is summary
    assert validated == []


def test_build_history_messages_without_references_carry_no_evidence_hint():
    context_msgs, recent = build_history_messages(_history(), "Goal: something", include_summary=True)
    assert len(context_msgs) == 2
    assert "get_session_summary_evidence" not in context_msgs[0]["content"]
    assert len(recent) == 8


def test_build_history_messages_with_references_appends_drill_back_hint():
    context_msgs, recent = build_history_messages(
        _history(),
        {"goal": "g", "findings": [], "actions_taken": [], "open_items": [], "state": "unknown"},
        include_summary=True,
        summary_references=["msg:m-1"],
    )
    assert len(context_msgs) == 2
    assert "<session_summary_json>" in context_msgs[0]["content"]
    assert "get_session_summary_evidence" in context_msgs[0]["content"]
    assert len(recent) == 8
