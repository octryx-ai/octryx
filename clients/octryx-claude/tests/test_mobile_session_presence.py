from __future__ import annotations

import json
import threading

from octryx_claude import mobile_summary, presence_heartbeat


def test_the_heartbeat_beats_while_the_session_runs_and_stops_after(state):
    beats = []
    done = threading.Event()

    def send(_state, _context, _http):
        beats.append(1)
        if len(beats) >= 3:
            done.set()
        return True

    with presence_heartbeat.running(state, object(), interval=0.01, send=send) as stop:
        assert done.wait(2)
    assert stop.is_set()
    count = len(beats)
    done.wait(0.05)
    assert len(beats) <= count + 1  # at most the beat in flight


def _transcript(tmp_path, entries):
    path = tmp_path / "t.jsonl"
    path.write_text("\n".join(json.dumps(entry) for entry in entries) + "\nnot json\n", encoding="utf-8")
    return path


def test_the_summary_is_the_first_prompt_and_the_last_answer_redacted(tmp_path):
    path = _transcript(tmp_path, [
        {"type": "user", "message": {"role": "user", "content": "<command-name>/clear</command-name>"}},
        {"type": "user", "message": {"role": "user", "content": "Refactor the pricing service\nand add tests"}},
        {"type": "assistant", "message": {"content": [{"type": "text", "text": "First answer"}]}},
        {"type": "user", "message": {"role": "user", "content": [{"type": "tool_result", "content": "x"}]}},
        {"type": "assistant", "message": {"content": [
            {"type": "tool_use", "name": "Bash"},
            {"type": "text", "text": "Done. I used token=ghp_abcdefghijklmnopqrstuvwxyz0123 to push."}]}},
    ])
    summary = mobile_summary.read_summary(path)
    assert summary["title"] == "Refactor the pricing service"
    assert "ghp_abcdefghijklmnopqrstuvwxyz" not in summary["last_text"] and "[REDACTED]" in summary["last_text"]
    assert summary["last_text"].startswith("Done.")


def test_no_transcript_no_summary(state, tmp_path):
    assert mobile_summary.stop_summary(state, {"transcript_path": str(tmp_path / "missing.jsonl")}) == {}
    assert mobile_summary.stop_summary(state, {}) == {}
    empty = _transcript(tmp_path, [])
    assert mobile_summary.read_summary(empty) == {}


def test_a_broken_transcript_or_config_never_reaches_the_stop_hook(state, tmp_path, monkeypatch):
    # The summary runs ahead of the verification call; nothing in it may raise
    deep = tmp_path / "deep.jsonl"
    deep.write_text("[" * 100_000 + "\n", encoding="utf-8")
    assert mobile_summary.read_summary(deep) == {}

    def broken(*_args, **_kwargs):
        raise RuntimeError("unexpected")

    monkeypatch.setattr(mobile_summary, "read_summary", broken)
    monkeypatch.setattr(mobile_summary, "transcript_inside", lambda *_args: tmp_path / "t.jsonl")
    assert mobile_summary.stop_summary(state, {"transcript_path": "x"}) == {}
    monkeypatch.setattr(type(state), "claude_config_dir", property(broken))
    assert mobile_summary.stop_summary(state, {"transcript_path": "x"}) == {}


def test_the_title_is_redacted_before_it_is_cut(tmp_path):
    secret = "ghp_" + "a" * 36
    path = _transcript(tmp_path, [
        {"type": "user", "message": {"role": "user", "content": "x" * 60 + f" token={secret} please"}},
    ])
    title = mobile_summary.read_summary(path)["title"]
    assert len(title) <= mobile_summary.MAX_TITLE and "ghp_" not in title
