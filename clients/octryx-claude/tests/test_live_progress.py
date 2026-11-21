"""Live progress, phase A (the phone showed nothing of a session until it answered):
what a listed session is doing, read-only from its own transcript, without thinking, file contents or secrets."""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

from octryx_claude import device_state, live_progress
from octryx_claude.live_progress import ProgressTail, events_from, transcript_path
from octryx_claude.state import LocalState
from tests.live_sessions_support import SESSION, _bridge

SID = "8f0c1d2e-aaaa-bbbb-cccc-000000000001"


def _line(**entry) -> str:
    return json.dumps({"timestamp": "2026-11-09T08:00:00Z", **entry})


def _assistant(*parts) -> str:
    return _line(type="assistant", message={"content": list(parts)})


def _user(content) -> str:
    return _line(type="user", message={"content": content})


def test_events_carry_narration_tools_and_results_but_no_thinking_or_file_contents():
    tools: dict[str, bool] = {}
    events = events_from([
        _user("Fix the failing test"),
        _assistant({"type": "thinking", "thinking": "secret reasoning"},
                   {"type": "text", "text": "I'll run the tests first."},
                   {"type": "tool_use", "id": "t1", "name": "Bash", "input": {"command": "npm test"}}),
        _user([{"type": "tool_result", "tool_use_id": "t1", "is_error": True,
                "content": "\n  2 failing\nAssertionError: expected 3"}]),
        _assistant({"type": "tool_use", "id": "t2", "name": "Read", "input": {"file_path": "/repo/.env"}}),
        _user([{"type": "tool_result", "tool_use_id": "t2", "content": "DB_PASSWORD=hunter2"}]),
        _assistant({"type": "tool_use", "id": "t3", "name": "Bash",
                    "input": {"command": "cd /repo && cat config.yml"}}),
        _user([{"type": "tool_result", "tool_use_id": "t3", "content": "api_key: abc"}]),
        _user([{"type": "tool_result", "tool_use_id": "unknown", "content": "whatever"}]),
    ], tools)
    kinds = [event["kind"] for event in events]
    assert kinds == ["prompt", "text", "tool", "result", "tool", "result", "tool", "result", "result"]
    assert "secret reasoning" not in json.dumps(events)
    assert events[2] == {"kind": "tool", "id": "t1", "tool": "Bash", "input": "npm test", "at": "2026-11-09T08:00:00Z"}
    assert events[3]["ok"] is False and events[3]["line"] == "2 failing"
    for quiet in (events[5], events[7], events[8]):  # Read, cat, an unknown call: no output at all
        assert "line" not in quiet
    assert "hunter2" not in json.dumps(events) and "abc" not in json.dumps(events)
    assert tools == {}


def test_secrets_are_redacted_and_texts_clipped():
    events = events_from([
        _assistant({"type": "text", "text": "Using token=ghp_" + "a" * 36 + " now. " + "x" * 2000}),
        _assistant({"type": "tool_use", "id": "t", "name": "Bash",
                    "input": {"command": "curl -H 'Authorization: Bearer abcdefghijklmnopqrstuvwxyz123456' x"}}),
        _user([{"type": "tool_result", "tool_use_id": "t", "content": "password=letmein ok"}]),
    ], {})
    text = json.dumps(events)
    assert "ghp_" not in text and "abcdefghijklmnopqrstuvwxyz123456" not in text and "letmein" not in text
    assert len(events[0]["text"]) <= live_progress.MAX_TEXT + 1


def test_prompts_from_other_sessions_show_but_the_phones_own_and_meta_do_not():
    events = events_from([
        _line(type="user", isMeta=True, origin={"kind": "peer", "name": "octryx", "body": "Status please"},
              message={"content": "<cross-session-message>…"}),
        _line(type="user", isMeta=True, origin={"kind": "peer", "name": "octryx-mobile", "body": "from the phone"},
              message={"content": "…"}),
        _line(type="user", isMeta=True, message={"content": "<system-reminder>…"}),
        _user("<command-name>/status</command-name>"),
        _line(type="assistant", isSidechain=True, message={"content": [{"type": "text", "text": "subagent"}]}),
        _line(type="system", subtype="compact_boundary"),
    ], {})
    assert [(e["kind"], e.get("from"), e.get("text")) for e in events] == [
        ("prompt", "octryx", "Status please"), ("compact", None, None)]


def _profile(home: Path, name: str = ".claude") -> Path:
    config = home / name
    (config / "sessions").mkdir(parents=True)
    (config / "projects" / "-Users-x-PRIV").mkdir(parents=True)
    return config


def test_the_transcript_is_found_only_inside_the_sessions_own_profile(tmp_path):
    home = tmp_path / "home"
    config = _profile(home)
    state = LocalState(tmp_path / "state")
    transcript = config / "projects" / "-Users-x-PRIV" / f"{SID}.jsonl"
    transcript.write_text("")
    session = {"profile": "default", "session_id": SID}
    assert transcript_path(state, session, home=home) == transcript.resolve()
    assert transcript_path(state, {"profile": "private", "session_id": SID}, home=home) is None
    assert transcript_path(state, {"profile": "default", "session_id": "../../etc/passwd"}, home=home) is None
    transcript.unlink()
    outside = tmp_path / "elsewhere.jsonl"
    outside.write_text("x")
    os.symlink(outside, transcript)  # a link leading out is never followed
    assert transcript_path(state, session, home=home) is None


def test_the_tail_reads_only_whats_new_and_waits_for_a_whole_line(tmp_path):
    home = tmp_path / "home"
    config = _profile(home)
    state = LocalState(tmp_path / "state")
    transcript = config / "projects" / "-Users-x-PRIV" / f"{SID}.jsonl"
    old = [_assistant({"type": "text", "text": f"old {n}"}) for n in range(100)]
    transcript.write_text("\n".join(old) + "\n")
    tail = ProgressTail(state, home=home)
    session = {**SESSION, "session_id": SID}
    [(peer, first)] = tail.collect([session])
    assert peer == SESSION["peer"] and len(first) == live_progress.FIRST_LOOK_EVENTS
    assert first[-1]["text"] == "old 99"
    assert tail.collect([session]) == []  # nothing new
    with transcript.open("a") as handle:
        handle.write(_assistant({"type": "text", "text": "new one"}) + "\n" + '{"type": "assist')
    [(_, new)] = tail.collect([session])
    assert [event["text"] for event in new] == ["new one"]
    with transcript.open("a") as handle:
        handle.write('ant", "message": {"content": [{"type": "text", "text": "finished"}]}}\n')
    [(_, rest)] = tail.collect([session])
    assert [event["text"] for event in rest] == ["finished"]
    transcript.write_text(_assistant({"type": "text", "text": "rewritten"}) + "\n")  # shorter: read anew
    [(_, again)] = tail.collect([session])
    assert [event["text"] for event in again] == ["rewritten"]
    assert tail.collect([]) == [] and tail._seen == {}  # a session that left the list is forgotten


def test_the_bridge_sends_progress_after_the_list_and_only_when_on(tmp_path, monkeypatch):
    bridge, channel = _bridge(tmp_path, True, [SESSION])
    monkeypatch.setattr(bridge.progress, "collect",
                        lambda sessions: [(SESSION["peer"], [{"kind": "text", "text": "hi"}])])
    asyncio.run(bridge.tick())
    kinds = [kind for kind, _ in channel.sent]
    assert kinds == ["live_sessions", "live_progress"]
    assert channel.sent[1][1] == {"peer": SESSION["peer"], "events": [{"kind": "text", "text": "hi"}]}
    config = bridge.state.config()
    config["live_progress"] = False
    bridge.state.ensure().write_config(config)
    asyncio.run(bridge.tick())
    assert [kind for kind, _ in channel.sent].count("live_progress") == 1
    device_state.save_device(bridge.state, {"device_id": "dev_1", "live": False})
    asyncio.run(bridge.tick())
    assert [kind for kind, _ in channel.sent].count("live_progress") == 1


SECRET_PRINTERS = [
    "aws secretsmanager get-secret-value --secret-id x --query SecretString --output text",
    "AWS_PROFILE=dev aws ssm get-parameter --name /x --with-decryption",
    "kubectl get secret app-secrets -o jsonpath='{.data.key}' | base64 -d",
    "kubectl -n octryx get secret app -o yaml",
    "kubectl describe secret app",
    "kubectl config view --raw",
    "vault kv get secret/app",
    "vault read -field=password secret/db",
    "gcloud secrets versions access latest --secret=x",
    "gcloud auth print-access-token",
    "op read op://vault/item/password",
    "op item get Login --fields password",
    "gh auth token",
    "printf 'host=github.com\\n' | git credential fill",
    "docker login -u x --password-stdin",
    "az keyvault secret show --name x --vault-name v",
    "doppler secrets get KEY --plain",
    "pass show work/db",
    "sops -d secrets.enc.yaml",
    "helm get values release -n ns",
    "cd /repo && aws sts get-session-token",
]


def test_commands_that_print_a_secret_never_send_their_output():
    for number, command in enumerate(SECRET_PRINTERS):
        tool_id = f"s{number}"
        events = events_from([
            _assistant({"type": "tool_use", "id": tool_id, "name": "Bash", "input": {"command": command}}),
            _user([{"type": "tool_result", "tool_use_id": tool_id, "content": "RAW-SECRET-VALUE-123"}]),
        ], {})
        assert "line" not in events[-1], command
        assert "RAW-SECRET-VALUE-123" not in json.dumps(events), command


def test_ordinary_commands_still_show_their_first_line():
    for number, command in enumerate(["npm test", "git status", "pytest -q", "ls -la", "kubectl get pods -n x",
                                      "aws s3 ls", "docker ps", "gh pr list"]):
        tool_id = f"o{number}"
        events = events_from([
            _assistant({"type": "tool_use", "id": tool_id, "name": "Bash", "input": {"command": command}}),
            _user([{"type": "tool_result", "tool_use_id": tool_id, "content": "first line\nsecond"}]),
        ], {})
        assert events[-1]["line"] == "first line", command
