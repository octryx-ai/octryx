"""/handoff on UserPromptSubmit, handoff_now, the stop hook and the automatic handoff notice."""

from __future__ import annotations

import io
import json

from octryx_claude import hooks, post_tool_use_hook, session_hooks
from octryx_claude.handoff_hooks import auto_handoff
from octryx_claude.platform import PlatformResult
from tests.handoff_support import KEY, Platform, context, repos  # noqa: F401

from .conftest import BASE_URL
from .gitrepo import requires_git

pytestmark = requires_git


# --- /handoff (UserPromptSubmit) ------------------------------------------------------------------------------------


def _env(monkeypatch):
    monkeypatch.setenv("OCTRYX_BASE_URL", BASE_URL)
    monkeypatch.setenv("OCTRYX_SESSION_KEY", KEY)
    monkeypatch.setenv("OCTRYX_WORKSPACE_ID", "ws-1")


# --- handoff_now ------------------------------------------------------------------------------------------------------


def _now(crossing="2026-10-06T10:00:00Z", **extra):
    return PlatformResult("ok", body={"handoff_now": True, "handoff_crossing": crossing, "handoff_trigger_pct": 99.0,
                                      **extra}, status_code=200)


def test_slash_handoff_runs_before_any_model_call_and_blocks_the_prompt(state, repos, monkeypatch, capsys):  # noqa: F811
    _env(monkeypatch)
    platform = Platform(repositories=[str(repos["remote"])])
    prompt = {"hook_event_name": "UserPromptSubmit", "prompt": "/handoff BRD-6 --note 'over to you'",
              "cwd": str(repos["user"])}
    monkeypatch.setattr("sys.stdin", io.TextIOWrapper(io.BytesIO(json.dumps(prompt).encode())))
    with platform.client() as http:
        assert session_hooks.run_user_prompt_submit(state, http) == 0
    output = json.loads(capsys.readouterr().out)

    assert output["decision"] == "block" and output["reason"].startswith("Octryx handoff: BRD-6: handoff v2")
    assert platform.paths() and all(path.startswith("/api/v1/agent-gateway/handoff/") for path in platform.paths())
    assert not any("model-gateway" in path or "messages" in path for path in platform.paths())
    assert json.loads(platform.requests[0].content)["key"] == "BRD-6" and platform.commits[0]["note"] == "over to you"


def test_other_prompts_pass_untouched_and_a_bad_handoff_never_reaches_the_model(state, monkeypatch, capsys):
    _env(monkeypatch)
    platform = Platform()
    for text in ("Please fix the handoff bug", "  /handoffs are great"):
        monkeypatch.setattr("sys.stdin", io.TextIOWrapper(io.BytesIO(json.dumps({"prompt": text}).encode())))
        with platform.client() as http:
            session_hooks.run_user_prompt_submit(state, http)
        assert capsys.readouterr().out == ""
    monkeypatch.setattr("sys.stdin", io.TextIOWrapper(io.BytesIO(json.dumps({"prompt": "/handoff --bogus"}).encode())))
    with platform.client() as http:
        session_hooks.run_user_prompt_submit(state, http)
    assert json.loads(capsys.readouterr().out)["decision"] == "block" and platform.requests == []


def test_handoff_now_hands_over_once_per_crossing(state, repos):  # noqa: F811
    platform = Platform(repositories=[str(repos["remote"])])
    with platform.client() as http:
        first = auto_handoff(state, context(), http, _now(), repos["user"])
        again = auto_handoff(state, context(), http, _now(), repos["user"])
        quiet = auto_handoff(state, context(), http, PlatformResult("ok", body={}), repos["user"])
        later = auto_handoff(state, context(), http, _now("2026-10-07T10:00:00Z"), repos["user"])
        asked = auto_handoff(state, context(), http, _now("requested-2026-10-08T10:00:00Z"), repos["user"])
    prepares = [request for request in platform.requests if request.url.path.endswith("/prepare")]

    assert first.startswith("Allowance at 99%: your work was handed over (BRD-6 → branch octryx-handoff/BRD-6/Anna-")
    assert first.endswith(" (pushed))")
    assert again == quiet == "" and later.startswith("Allowance at 99%") and asked.startswith("A Workspace admin")
    assert len(prepares) == 3 and all(json.loads(request.content)["all"] is True for request in prepares)


def test_the_stop_hook_hands_over_and_does_not_nudge_afterwards(state, repos, monkeypatch, capsys):  # noqa: F811
    _env(monkeypatch)
    platform = Platform(repositories=[str(repos["remote"])])
    answer = _now(state="passed", handoff_nudges=[{"work_item_key": "BRD-6", "marker": "c1:-:0"}])
    answer = PlatformResult("ok", body={**answer.body, "state": "passed"}, status_code=200, state="passed")
    monkeypatch.setattr(hooks, "call_control_plane", lambda *args, **kwargs: answer)
    stop = {"hook_event_name": "Stop", "session_id": "s1", "stop_hook_active": False, "cwd": str(repos["user"])}
    monkeypatch.setattr("sys.stdin", io.TextIOWrapper(io.BytesIO(json.dumps(stop).encode())))
    with platform.client() as http:
        hooks.run_stop(state, http)
    output = json.loads(capsys.readouterr().out)
    assert "decision" not in output and output["systemMessage"].startswith("Allowance at 99%: your work was handed")


def test_post_tool_use_shows_the_automatic_handoff_notice(state, repos, monkeypatch, capsys):  # noqa: F811
    _env(monkeypatch)
    platform = Platform(repositories=[str(repos["remote"])])
    monkeypatch.setattr(post_tool_use_hook, "call_control_plane", lambda *args, **kwargs: _now())
    event = {"hook_event_name": "PostToolUse", "tool_name": "Bash", "tool_use_id": "t1", "cwd": str(repos["user"])}
    monkeypatch.setattr("sys.stdin", io.TextIOWrapper(io.BytesIO(json.dumps(event).encode())))
    with platform.client() as http:
        post_tool_use_hook.run_post_tool_use(state, http)
    assert json.loads(capsys.readouterr().out)["systemMessage"].startswith("Allowance at 99%")
