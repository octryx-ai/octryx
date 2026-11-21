"""The hook runners send the session contract, report tool use and session end, and send a failed check once more."""

from __future__ import annotations

import io
import json

import httpx

from octryx_claude import hooks, post_tool_use_hook, pre_tool_use_hook, session_hooks
from tests.hooks_support import KEY, _decision, _ok

from .conftest import BASE_URL


def _hook_env(monkeypatch, hook_input: dict) -> None:
    monkeypatch.setattr("sys.stdin", io.TextIOWrapper(io.BytesIO(json.dumps(hook_input).encode())))
    monkeypatch.setenv("OCTRYX_BASE_URL", BASE_URL)
    monkeypatch.setenv("OCTRYX_SESSION_KEY", KEY)
    monkeypatch.setenv("OCTRYX_WORKSPACE_ID", "ws-1")
    monkeypatch.delenv("OCTRYX_WORK_ITEM", raising=False)


def test_pre_tool_use_runner_sends_the_session_contract(state, monkeypatch, capsys):
    hook_input = {"hook_event_name": "PreToolUse", "tool_name": "Bash",
                  "tool_input": {"command": "git push origin main"}}
    monkeypatch.setattr("sys.stdin", io.TextIOWrapper(io.BytesIO(json.dumps(hook_input).encode())))
    monkeypatch.setenv("OCTRYX_BASE_URL", BASE_URL)
    monkeypatch.setenv("OCTRYX_SESSION_KEY", KEY)
    monkeypatch.setenv("OCTRYX_WORKSPACE_ID", "ws-1")
    monkeypatch.delenv("OCTRYX_WORK_ITEM", raising=False)
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"decision": "deny", "state": "denied", "reason": "command_prefix_denied",
                                         "rule_id": "no-push-to-main"})

    assert pre_tool_use_hook.run_pre_tool_use(state, httpx.Client(transport=httpx.MockTransport(handler))) == 0

    request = seen[0]
    assert str(request.url) == f"{BASE_URL}/api/v1/agent-gateway/sessions/tool-check"
    assert request.headers["authorization"] == "Bearer gw-cached"
    assert request.headers["x-octryx-session"] == KEY
    assert request.headers["x-octryx-workspace"] == "ws-1"
    assert json.loads(request.content) == hook_input
    assert _decision(json.loads(capsys.readouterr().out)) == "deny"


def test_post_tool_use_reports_execution_silently_and_never_blocks(state, monkeypatch, capsys):
    hook_input = {"hook_event_name": "PostToolUseFailure", "tool_name": "Bash", "tool_use_id": "toolu_01",
                  "tool_input": {"command": "pytest -q"}, "error": "Exit code 1", "is_interrupt": False}
    monkeypatch.setenv("OCTRYX_BASE_URL", BASE_URL)
    monkeypatch.setenv("OCTRYX_SESSION_KEY", KEY)
    monkeypatch.setenv("OCTRYX_WORKSPACE_ID", "ws-1")
    seen: list[httpx.Request] = []

    def run(status: int) -> int:
        monkeypatch.setattr("sys.stdin", io.TextIOWrapper(io.BytesIO(json.dumps(hook_input).encode())))

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return httpx.Response(status, json={"state": "recorded", "reason": "execution_recorded_new_row"})

        return post_tool_use_hook.run_post_tool_use(state, httpx.Client(transport=httpx.MockTransport(handler)))

    assert run(200) == 0 and run(500) == 0
    assert str(seen[0].url) == f"{BASE_URL}/api/v1/agent-gateway/sessions/tool-executed"
    assert seen[0].headers["x-octryx-session"] == KEY
    assert json.loads(seen[0].content) == hook_input
    assert capsys.readouterr().out == ""


def test_post_tool_use_forwards_a_native_read_unchanged_for_the_platforms_read_evidence(state, monkeypatch, capsys):
    # The platform derives what was read (and whether it lies in the repository) from tool_input and cwd itself.
    hook_input = {"hook_event_name": "PostToolUse", "tool_name": "Read", "tool_use_id": "toolu_02",
                  "cwd": "/work/textkit", "tool_input": {"file_path": "/work/textkit/textkit/core.py"},
                  "tool_response": {"type": "text", "file": {"content": "def wrap(): ..."}}}
    monkeypatch.setenv("OCTRYX_BASE_URL", BASE_URL)
    monkeypatch.setenv("OCTRYX_SESSION_KEY", KEY)
    monkeypatch.setenv("OCTRYX_WORKSPACE_ID", "ws-1")
    monkeypatch.setattr("sys.stdin", io.TextIOWrapper(io.BytesIO(json.dumps(hook_input).encode())))
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"state": "recorded", "reason": "execution_recorded_new_row"})

    assert post_tool_use_hook.run_post_tool_use(state, httpx.Client(transport=httpx.MockTransport(handler))) == 0
    assert seen[0].url.path == "/api/v1/agent-gateway/sessions/tool-executed"
    assert json.loads(seen[0].content) == hook_input
    assert capsys.readouterr().out == ""


def test_session_end_posts_a_redacted_digest_built_by_the_shared_ingest_code(state, monkeypatch):
    transcript = state.claude_config_dir / "projects" / "p" / "t.jsonl"
    transcript.parent.mkdir(parents=True)
    lines = [
        {"type": "user", "cwd": "/w", "message": {"role": "user", "content": (
            "deploy with api_key=abcd" + "ef123456"
        )}},
        {"type": "assistant", "message": {"role": "assistant", "content": [{"type": "text", "text": "Done."}]}},
    ]
    transcript.write_text("\n".join(json.dumps(line) for line in lines))
    hook_input = {"hook_event_name": "SessionEnd", "transcript_path": str(transcript), "cwd": "/w",
                  "session_id": KEY, "reason": "prompt_input_exit"}
    monkeypatch.setattr("sys.stdin", io.TextIOWrapper(io.BytesIO(json.dumps(hook_input).encode())))
    monkeypatch.setenv("OCTRYX_BASE_URL", BASE_URL)
    monkeypatch.setenv("OCTRYX_SESSION_KEY", KEY)
    monkeypatch.setenv("OCTRYX_WORKSPACE_ID", "ws-1")
    bodies: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/agent-gateway/sessions/finalize"
        bodies.append(json.loads(request.content))
        return httpx.Response(200, json={"state": "finalized", "external_session_id": "s-1"})

    assert session_hooks.run_session_end(state, httpx.Client(transport=httpx.MockTransport(handler))) == 0

    body = bodies[0]
    assert "[USER] deploy with api_key=[REDACTED]" in body["transcript_digest"]
    assert ("abcd" + "ef123456") not in json.dumps(body)
    assert "[ASSISTANT] Done." in body["transcript_digest"]
    assert body["claude_session_id"] == KEY and body["workspace_ref"] == "/w"


def test_a_tool_check_that_could_not_connect_is_sent_once_more_and_then_fails_closed(state, monkeypatch, capsys):
    """A platform the hook cannot reach (e.g. during a deploy) gets one retry after a short pause; still unreachable:
    denied."""
    from octryx_claude import platform

    monkeypatch.setattr(platform.time, "sleep", lambda _seconds: None)
    _hook_env(monkeypatch, {"hook_event_name": "PreToolUse", "tool_name": "Read", "tool_input": {"file_path": "a"}})
    answers = [httpx.ConnectError("refused"), httpx.Response(200, json={"decision": "allow", "state": "allowed"})]

    def handler(request: httpx.Request) -> httpx.Response:
        answer = answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer

    assert pre_tool_use_hook.run_pre_tool_use(state, httpx.Client(transport=httpx.MockTransport(handler))) == 0
    assert capsys.readouterr().out == "" and answers == []  # allowed on the second call

    _hook_env(monkeypatch, {"hook_event_name": "PreToolUse", "tool_name": "Read", "tool_input": {"file_path": "a"}})
    calls = []

    def down(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(503, text="no available server")  # the ingress, not the gateway

    assert pre_tool_use_hook.run_pre_tool_use(state, httpx.Client(transport=httpx.MockTransport(down))) == 0
    output = json.loads(capsys.readouterr().out)
    assert len(calls) == 2 and _decision(output) == "deny"
    assert "fail closed" in output["hookSpecificOutput"]["permissionDecisionReason"]


def test_a_gateway_refusal_or_a_read_timeout_is_never_sent_twice(state, monkeypatch):
    """Only a call that never reached the platform is repeated: the gateway's own answer, or a call it may have acted
    on (read timeout), stands."""
    from octryx_claude import platform

    monkeypatch.setattr(platform.time, "sleep", lambda _seconds: None)
    context = platform.SessionContext(BASE_URL, KEY, "ws-1")
    for answer in (httpx.Response(503, headers={"x-octryx-gateway-state": "denied"}),
                   httpx.ReadTimeout("slow"), httpx.Response(403)):
        calls = []

        def handler(request: httpx.Request, answer=answer) -> httpx.Response:
            calls.append(request)
            if isinstance(answer, Exception):
                raise answer
            return answer

        result = platform.call_control_plane(state, context, "POST", "/sessions/tool-check", timeout=1.0, retry=True,
                                             http=httpx.Client(transport=httpx.MockTransport(handler)))
        assert len(calls) == 1 and result.outcome in ("refused", "unreachable")
    result = platform.call_control_plane(state, context, "POST", "/x", timeout=1.0, http=httpx.Client(
        transport=httpx.MockTransport(lambda request: (_ for _ in ()).throw(httpx.ConnectError("down")))))
    assert (result.outcome, result.reason) == ("unreachable", "platform_unreachable")  # the code stays the same


def test_claude_codes_own_compaction_helper_is_never_gated(state, monkeypatch, capsys):
    """Claude Code sends ``agent_type: ""`` for its own forks (its compaction): never gated. A Task agent (a type) and
    a SubagentStop without the field stay gated."""
    posted = []
    monkeypatch.setattr(hooks, "call_control_plane", lambda *args, **kwargs: posted.append(args) or _ok(
        {"state": "blocked", "detail": "Not done."}))
    compaction = {"hook_event_name": "SubagentStop", "agent_id": "a1", "agent_type": "", "stop_hook_active": False,
                  "agent_transcript_path": "/tmp/none.jsonl"}
    _hook_env(monkeypatch, compaction)
    assert hooks.run_stop(state, httpx.Client()) == 0
    assert capsys.readouterr().out == "" and posted == []

    for hook_input in ({**compaction, "agent_type": "general-purpose"},
                       {key: value for key, value in compaction.items() if key != "agent_type"}):
        _hook_env(monkeypatch, hook_input)
        assert hooks.run_stop(state, httpx.Client()) == 0
        assert json.loads(capsys.readouterr().out)["decision"] == "block"
    assert len(posted) == 2


def test_a_browser_call_the_platform_allowed_still_stays_on_the_apps_loopback(state, monkeypatch, capsys):
    """The hook denies a browser URL off loopback (or on the platform's own port) for Claude
    Code and Codex alike, also when the platform said allow; the platform is still asked (and records the call)."""
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"decision": "allow", "state": "allowed"})

    def decide(url: str, base_url: str = BASE_URL) -> str:
        _hook_env(monkeypatch, {"hook_event_name": "PreToolUse", "tool_name": "mcp__playwright__browser_navigate",
                                "tool_input": {"url": url}, "tool_use_id": "toolu_b"})
        monkeypatch.setenv("OCTRYX_BASE_URL", base_url)
        pre_tool_use_hook.run_pre_tool_use(state, httpx.Client(transport=httpx.MockTransport(handler)))
        out = capsys.readouterr().out
        return _decision(json.loads(out)) if out else "allow"

    assert decide("https://example.com/") == "deny"
    assert decide("http://127.0.0.1:8765/menu") == "allow"
    assert decide("http://localhost:3000/") == "allow"
    assert len(seen) == 3  # every call went to the platform first
