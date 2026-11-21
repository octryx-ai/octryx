"""Lessons learned, the client's side: paths not contents, secrets out, one ref per compaction,
opt-out."""

from __future__ import annotations

import json

from octryx_claude import launch_settings, session_lessons
from octryx_claude.state import LocalState

AWS = "AKIAIOSFODNN7EXAMPLE"
KEY = "-----BEGIN OPENSSH PRIVATE KEY-----\nb3BlbnNzaC1rZXktdjEAAAAA\n-----END OPENSSH PRIVATE KEY-----"


def _transcript(tmp_path):
    path = LocalState(tmp_path / "s").claude_config_dir / "projects" / "p" / "t.jsonl"  # octryx's own dir
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(entry) for entry in [
        {"type": "user", "message": {"role": "user", "content": f"Deploy with key {AWS}"}},
        {"type": "assistant", "message": {"content": [
            {"type": "tool_use", "id": "w", "name": "Write",
             "input": {"file_path": "/repo/a.py", "content": "SECRET"}}]}},
    ]))
    return path


def test_body_holds_paths_and_redacted_text_with_a_stable_ref(tmp_path):
    state = LocalState(tmp_path / "s")
    hook = {"session_id": "s-1", "transcript_path": str(_transcript(tmp_path)),
            "compact_summary": f"We used password=hunter2 and {KEY}."}
    body = session_lessons.lessons_body(state, hook, kind="compact")
    text = json.dumps(body)
    assert AWS not in text and "hunter2" not in text and "PRIVATE KEY" not in text and "SECRET" not in text
    assert body["facts"]["files"] == ["/repo/a.py"] and "[redacted]" in body["summary"]
    assert body["ref"].startswith("com-") and len(body["ref"]) <= 48
    assert session_lessons.lessons_body(state, hook, kind="compact")["ref"] == body["ref"]  # a retry: same ref
    assert session_lessons.lessons_body(state, hook, kind="end")["summary"] is None  # the end sends facts only


def test_opt_out_sends_nothing(tmp_path, monkeypatch):
    state = LocalState(tmp_path / "s").ensure()
    hook = {"session_id": "s-1", "transcript_path": str(_transcript(tmp_path))}
    state.write_config({"session_lessons": False})
    assert session_lessons.lessons_body(state, hook, kind="end") is None
    state.write_config({})
    monkeypatch.setenv("OCTRYX_SESSION_LESSONS", "0")
    assert session_lessons.lessons_body(state, hook, kind="end") is None


def test_post_compact_hook_is_registered():
    from pathlib import Path

    settings = launch_settings.build_settings(shim=Path("/bin/octryx-claude"), state_root=Path("/s"), env={},
                                     policy={"state": "allowed"}, base_url="https://octryx.example.test")
    assert settings["hooks"]["PostCompact"][0]["hooks"][0]["command"].endswith("hook post-compact")
