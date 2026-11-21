"""Background agents of a plain run turn: Claude Code stops a background agent 600 s after the main session's Stop
and sends no completion notice; an agent resumed with SendMessage runs again. Transcript shapes as Claude Code writes
them."""

from __future__ import annotations

import json
import time
from pathlib import Path

from octryx_claude import turn_idle

AGENT = "ad20a90c442c6fc2b"


def _iso(at: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(at)) + f".{int(at % 1 * 1000):03d}Z"


def _launch(at: float, agent: str = AGENT) -> dict:
    return {"type": "user", "timestamp": _iso(at),
            "toolUseResult": {"isAsync": True, "status": "async_launched", "agentId": agent}}


def _resume(at: float, agent: str = AGENT) -> dict:
    return {"type": "user", "timestamp": _iso(at), "toolUseResult": {"success": True, "resumedAgentId": agent}}


def _notice(at: float, status: str, agent: str = AGENT) -> dict:
    return {"type": "queue-operation", "operation": "enqueue", "timestamp": _iso(at),
            "content": f"<task-notification>\n<task-id>{agent}</task-id>\n<status>{status}</status>\n"}


def _write(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row) + "\n" for row in rows))


def _agent_rows(at: float, *, interrupted: bool) -> list[dict]:
    rows = [{"type": "assistant", "timestamp": _iso(at), "message": {"role": "assistant", "content": [
        {"type": "tool_use", "id": "t1", "name": "Bash", "input": {"command": "flutter test"}}]}}]
    if interrupted:
        rows.append({"type": "user", "timestamp": _iso(at + 1), "message": {"role": "user", "content": [
            {"type": "text", "text": "[Request interrupted by user]"}]}})
    return rows


def _session(tmp_path: Path) -> tuple[Path, Path]:
    transcript = tmp_path / "89aa3f23.jsonl"
    return transcript, tmp_path / "89aa3f23" / "subagents" / f"agent-{AGENT}.jsonl"


def test_an_agent_claude_code_stopped_is_over_and_named(tmp_path):
    at = time.time() - 1000
    transcript, agent = _session(tmp_path)
    _write(transcript, [_launch(at)])
    _write(agent, _agent_rows(at + 600, interrupted=False))
    assert turn_idle.open_tasks(transcript, at - 1) == {AGENT}  # still working
    assert turn_idle.stopped_agents(transcript, at - 1) == set()
    _write(agent, _agent_rows(at + 600, interrupted=True))
    assert turn_idle.open_tasks(transcript, at - 1) == set()
    assert turn_idle.stopped_agents(transcript, at - 1) == {AGENT}
    note = turn_idle.STOPPED_AGENT_NOTE.format(agents=AGENT)
    assert "stopped by Claude Code 10 min after the main session ended" in note and "incomplete" in note


def test_an_agent_resumed_with_send_message_runs_again_until_its_notice(tmp_path):
    """A "stopped" notice from before a SendMessage resume does not end the resumed agent's turn."""
    at = time.time() - 1000
    transcript, agent = _session(tmp_path)
    _write(agent, _agent_rows(at - 2000, interrupted=True) + _agent_rows(at + 15, interrupted=False))
    _write(transcript, [_notice(at, "stopped"), _resume(at + 11)])
    assert turn_idle.open_tasks(transcript, at - 1) == {AGENT}
    assert turn_idle.stopped_agents(transcript, at - 1) == set()
    _write(transcript, [_notice(at, "stopped"), _resume(at + 11), _notice(at + 90, "completed")])
    assert turn_idle.open_tasks(transcript, at - 1) == set()


def test_an_agent_without_a_transcript_counts_as_running(tmp_path):
    at = time.time() - 1000
    transcript, _agent = _session(tmp_path)
    _write(transcript, [_launch(at, "a5f9f261e1abb0771")])
    assert turn_idle.open_tasks(transcript, at - 1) == {"a5f9f261e1abb0771"}


def test_the_turn_ended_while_waiting_says_which_agent_claude_code_stopped(tmp_path):
    import asyncio

    from octryx_claude.plain_driver import PlainCliDriver

    at = time.time() - 1000
    transcript, agent = _session(tmp_path)
    answer = {"type": "assistant", "timestamp": _iso(at + 5), "message": {"content": [
        {"type": "text", "text": "Backend done; waiting for the frontend agent."}]}}
    _write(transcript, [_launch(at), answer])
    _write(agent, _agent_rows(at + 600, interrupted=True))
    driver, events, result = PlainCliDriver(), [], {"status": "error", "result_text": ""}
    driver._only_waiting = transcript

    async def emit(event):
        events.append(event)

    asyncio.run(driver._finished_while_waiting(result, at - 1, "cs-1", emit))
    assert result["status"] == "success"
    assert result["result_text"].startswith("Backend done; waiting for the frontend agent.")
    assert f"its work is incomplete: {AGENT}." in result["result_text"]
    assert "stopped by Claude Code" in events[-1]["text"]
