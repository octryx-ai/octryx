"""The independent reviewer's call on this device's seat is one tool-less model call.

The platform cannot reach a person's subscription by itself, so a seat review runs here: the request comes from the
platform, the call has no tools, no MCP server, no settings of the folder or history, and the answer goes back."""

from __future__ import annotations

import asyncio
import base64
import json
from pathlib import Path

import pytest

from octryx_claude import review_call
from octryx_claude.device_session import PreparedSession
from octryx_claude.review_call import ReviewCallDriver, claude_command, claude_message, claude_result, codex_command

PNG = b"\x89PNG\r\n\x1a\nfake"


def _prepared(tmp_path: Path, cli: str = "claude") -> PreparedSession:
    return PreparedSession(session_key="00000000-0000-4000-8000-0000000000ee", cli_path=cli,
                           settings_path=tmp_path / "settings.json", mcp_path=tmp_path / "mcp.json",
                           env={"X": "1"}, profile="seat", model="claude-haiku-5-5", extra={})


def _request(**extra) -> dict:
    return {"turn_id": "t1", "system": "You are the independent reviewer.", "user": "Review this change.",
            "images": [{"name": "home.png", "media_type": "image/png", "data": base64.b64encode(PNG).decode()}],
            "model": "claude-haiku-5-5", "engine": "claude_code", **extra}


def test_the_claude_call_has_no_tools_no_mcp_no_settings_sources_and_no_history(tmp_path):
    args = claude_command(_prepared(tmp_path), system="SYS", model="claude-haiku-5-5")
    assert args[:2] == ["claude", "-p"]
    assert args[args.index("--tools") + 1] == ""  # no built-in tool at all
    assert json.loads(args[args.index("--mcp-config") + 1]) == {"mcpServers": {}} and "--strict-mcp-config" in args
    assert args[args.index("--setting-sources") + 1] == ""  # no CLAUDE.md, no project or user settings
    assert args[args.index("--system-prompt") + 1] == "SYS" and args[args.index("--model") + 1] == "claude-haiku-5-5"
    assert "--resume" not in args and "--continue" not in args  # a fresh session every call
    message = json.loads(claude_message("TASK", _request()["images"]))["message"]
    assert [part["type"] for part in message["content"]] == ["text", "text", "image"]
    assert message["content"][1]["text"] == "Screenshot: home.png"


def test_the_codex_call_runs_read_only_in_an_empty_folder_without_a_thread():
    args = codex_command("codex", cwd="/tmp/empty", model="gpt-6-luna", images=["/tmp/a.png"], answer_file="/tmp/o")
    assert args[:3] == ["codex", "exec", "--json"] and "--ephemeral" in args and "resume" not in args
    assert args[args.index("--sandbox") + 1] == "read-only" and args[args.index("-C") + 1] == "/tmp/empty"
    assert args[args.index("--image") + 1] == "/tmp/a.png" and args[args.index("-m") + 1] == "gpt-6-luna"


def test_the_answer_usage_and_model_come_from_the_result_line():
    lines = [json.dumps({"type": "system", "subtype": "init", "model": "claude-haiku-5-5"}),
             json.dumps({"type": "result", "result": '{"verdict": "pass"}', "usage": {
                 "input_tokens": 10, "cache_read_input_tokens": 5, "output_tokens": 7}})]
    assert claude_result(lines) == {"text": '{"verdict": "pass"}', "model": "claude-haiku-5-5",
                                    "usage": {"input_tokens": 15, "output_tokens": 7}}
    with pytest.raises(review_call.ReviewCallError):
        claude_result([json.dumps({"type": "result", "is_error": True})])


def test_the_driver_fetches_the_request_answers_it_and_posts_the_answer(tmp_path, monkeypatch):
    calls: list[tuple] = []

    def control(method, path, body):
        calls.append((method, path, body))
        return (True, _request()) if method == "GET" else (True, {"state": "recorded"})

    ran: list[dict] = []

    async def run(args, *, cwd, env, stdin, started=None):
        ran.append({"args": args, "cwd": cwd, "stdin": stdin})
        assert not any(Path(cwd).iterdir())  # an empty folder: nothing of the repository to read
        return 0, [json.dumps({"type": "result", "result": '{"verdict": "pass"}',
                               "usage": {"input_tokens": 3, "output_tokens": 2}})]

    monkeypatch.setattr(review_call, "_run", run)
    result = asyncio.run(ReviewCallDriver(control).run_turn(_prepared(tmp_path), cwd=str(tmp_path), prompt="p",
                                                            resume="earlier-session"))
    assert result["status"] == "success" and "verdict" not in result["result_text"]  # the chat gets no answer
    assert [call[:2] for call in calls] == [("GET", "/review-request"), ("POST", "/review-answer")]
    assert calls[1][2] == {"turn_id": "t1", "text": '{"verdict": "pass"}', "model": "claude-haiku-5-5",
                           "usage": {"input_tokens": 3, "output_tokens": 2}}
    assert ran[0]["cwd"] != str(tmp_path) and "--resume" not in ran[0]["args"]  # never the folder or the session


def test_no_request_means_no_call(tmp_path, monkeypatch):
    monkeypatch.setattr(review_call, "_run", lambda *a, **k: pytest.fail("no call without a request"))
    result = asyncio.run(ReviewCallDriver(lambda *a: (False, "review_request_not_found")).run_turn(
        _prepared(tmp_path), cwd=str(tmp_path), prompt="p", resume=None))
    assert result == {"status": "error", "error": "review_request_unavailable"}


def test_a_failed_codex_review_call_names_a_seat_limit_and_logs_codex_s_error(caplog):
    """A failed Codex review call names a seat limit, and Codex's error is in the log."""
    import json
    import logging

    from octryx_claude.review_call import codex_failure

    limit = json.dumps({"type": "turn.failed", "error": {"type": "usage_limit_reached", "message": "You've hit your"
                                                                                                  " usage limit."}})
    assert codex_failure(["not json", limit]) == "usage_limit"
    other = json.dumps({"type": "error", "message": "stream disconnected before completion"})
    with caplog.at_level(logging.WARNING, logger="octryx_claude.device.review"):
        assert codex_failure([other]) == ""
    assert "stream disconnected before completion" in caplog.text
