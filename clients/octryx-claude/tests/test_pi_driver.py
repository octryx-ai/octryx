"""The pi harness: a governed chat turn on pi instead of Claude Code, through the same gateway."""

from __future__ import annotations

import asyncio
import json
import stat
from pathlib import Path
from types import SimpleNamespace

from octryx_claude.pi_driver import PiDriver, Usage, chosen_harness, map_event, models_config, uses_pi

EVENTS = [
    {"type": "session", "version": 3, "id": "pi-session-1", "cwd": "/w"},
    {"type": "agent_start"},
    {"type": "message_update", "assistantMessageEvent": {"type": "text_delta", "delta": "Look"}},
    {"type": "message_end", "message": {"role": "assistant", "content": [{"type": "text", "text": "Looking."}],
                                        "usage": {"input": 1000, "output": 50, "cacheRead": 0, "cacheWrite": 0,
                                                  "totalTokens": 1050, "cost": {"total": 0.001}}}},
    {"type": "tool_execution_start", "toolCallId": "t1", "toolName": "bash", "args": {"command": "pytest -q"}},
    {"type": "tool_execution_end", "toolCallId": "t1", "toolName": "bash", "isError": False,
     "result": {"content": [{"type": "text", "text": "3 passed"}]}},
    {"type": "message_end", "message": {"role": "assistant", "content": [{"type": "text", "text": "Done: 3 pass."}],
                                        "usage": {"input": 1200, "output": 30, "totalTokens": 1230,
                                                  "cost": {"total": 0.002}}}},
    {"type": "agent_end", "messages": []},
]


def _fake_pi(tmp_path: Path) -> Path:
    """A ``pi`` that records its argv, cwd and config, and prints the JSON stream."""
    script = tmp_path / "pi"
    script.write_text("#!/usr/bin/env python3\nimport json, os, sys\n"
                      f"open({str(tmp_path / 'call.json')!r}, 'w').write(json.dumps({{'argv': sys.argv[1:], "
                      "'cwd': os.getcwd(), 'models': json.load(open(os.path.join(os.environ['PI_CODING_AGENT_DIR'], "
                      "'models.json')))}))\n"
                      f"for line in {json.dumps([json.dumps(item) for item in EVENTS])!r}:\n    print(line)\n"
                      .replace("for line in '", "for line in json.loads('").replace("':\n    print", "'):\n    print"))
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    return script


def _prepared(tmp_path: Path) -> SimpleNamespace:
    settings = tmp_path / "settings.json"
    settings.write_text(json.dumps({"apiKeyHelper": "/opt/shim api-key-helper"}))
    return SimpleNamespace(
        session_key="sk-1", settings_path=settings, model="gemma-4-31b", extra={"context_window": 200000},
        env={"ANTHROPIC_BASE_URL": "https://octryx.example/api/v1/model-gateway",
             "ANTHROPIC_CUSTOM_HEADERS": "X-Octryx-Session: sk-1\nX-Octryx-Workspace: ws-1",
             "ANTHROPIC_MODEL": "gemma-4-31b", "ANTHROPIC_API_KEY": ""})


def test_pi_is_opt_in_per_device_and_only_for_governed_chat_turns(tmp_path):
    assert chosen_harness(tmp_path) == {} and not uses_pi(tmp_path, {"profile": "governed"})
    (tmp_path / "harness.json").write_text(json.dumps({"harness": "pi"}))
    assert uses_pi(tmp_path, {"profile": "governed", "workflow_run": ""})
    assert not uses_pi(tmp_path, {"profile": "governed", "workflow_run": "run-1"})  # phase checks need the hooks
    assert not uses_pi(tmp_path, {"profile": "local:work"})


def test_the_model_goes_through_the_gateway_with_the_session_headers_and_no_stored_key():
    env = _prepared(Path("/tmp")).env
    provider = models_config(env, model="gemma-4-31b", key_command="/opt/shim api-key-helper",
                             context_window=200000)["providers"]["octryx"]
    assert (provider["baseUrl"], provider["api"]) == (
        "https://octryx.example/api/v1/model-gateway", "anthropic-messages"
    )
    assert provider["headers"] == {"X-Octryx-Session": "sk-1", "X-Octryx-Workspace": "ws-1"}
    assert provider["apiKey"] == "!/opt/shim api-key-helper"  # pi runs the helper; nothing secret on disk


def test_events_map_to_the_chats_job_events_and_usage_adds_up():
    usage, last = Usage(), {"text": ""}
    events = [item for event in EVENTS for item in map_event(event, usage, last)]
    assert [item["kind"] for item in events] == ["session", "text_delta", "text", "tool_use", "tool_result", "text"]
    assert events[3]["tool"] == "bash" and events[4]["output"] == "3 passed"
    assert usage.as_claude()["input_tokens"] == 2200 and round(usage.cost, 3) == 0.003
    assert last["text"] == "Done: 3 pass."


def test_a_turn_runs_pi_in_the_folder_and_continues_its_session(tmp_path):
    pi = _fake_pi(tmp_path)
    driver = PiDriver(tmp_path / "state", {"harness": "pi", "pi_path": str(pi)})
    emitted: list[dict] = []

    async def emit(event):
        emitted.append(event)

    work = tmp_path / "work"
    work.mkdir()
    result = asyncio.run(driver.run_turn(_prepared(tmp_path), cwd=str(work), prompt="Do T8.", resume="pi-session-0",
                                         emit=emit))
    call = json.loads((tmp_path / "call.json").read_text())
    assert call["cwd"] == str(work.resolve()) or call["cwd"] == str(work)
    assert call["argv"][:5] == ["--mode", "json", "-p", "--model", "octryx/gemma-4-31b"]
    assert call["argv"][-3:] == ["--session", "pi-session-0", "Do T8."]
    assert call["models"]["providers"]["octryx"]["apiKey"] == "!/opt/shim api-key-helper"
    assert (result["status"], result["result_text"], result["claude_session_id"]) == (
        "success", "Done: 3 pass.", "pi-session-1")
    assert result["usage"]["output_tokens"] == 80
    assert {"kind": "context", "tokens": 1230} in emitted
