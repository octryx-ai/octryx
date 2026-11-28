from __future__ import annotations

import asyncio
import json
from pathlib import Path

from octryx_claude.plain_driver import PlainCliDriver
from tests.plain_driver_support import _prepared


def _replay_setup(tmp_path, monkeypatch, script: str):
    from octryx_claude import hooks
    from octryx_claude.platform import SessionContext
    from octryx_claude.state import LocalState

    state = LocalState(tmp_path / "home").ensure()
    key = "00000000-0000-4000-8000-0000000000dd"
    monkeypatch.setenv(hooks.DEFER_STOP_ENV, "1")
    context = SessionContext("https://octryx.example.test", key, "ws", "", "")
    hooks._defer_stop(state, context, {"hook_event_name": "Stop"})
    shim = tmp_path / "shim"
    shim.write_text(script)
    shim.chmod(0o755)
    prepared = _prepared(tmp_path)
    prepared.env.update({"OCTRYX_CLAUDE_HOME": str(tmp_path / "home"), "OCTRYX_TEST_RUN_SHIM": str(shim)})
    return state, key, prepared


def _transcript_rows(at: float, *, notified: bool) -> list[dict]:
    from datetime import UTC, datetime

    def stamp(offset: float) -> str:
        return datetime.fromtimestamp(at + offset, UTC).isoformat().replace("+00:00", "Z")

    rows = [{"type": "user", "timestamp": stamp(0.1), "toolUseResult": {"isAsync": True, "status": "async_launched",
                                                                        "agentId": "a9f49e228f6b2d0eb"}},
            {"type": "assistant", "timestamp": stamp(0.2), "message": {"content": [
                {"type": "tool_use", "name": "ScheduleWakeup", "input": {"delaySeconds": 1200}}]}}]
    if notified:
        rows.append({"type": "queue-operation", "operation": "enqueue", "timestamp": stamp(0.3),
                     "content": "<task-notification>\n<task-id>a9f49e228f6b2d0eb</task-id>\n"
                                "<status>completed</status>"})
    rows.append({"type": "assistant", "timestamp": stamp(0.4),
                 "message": {"content": [{"type": "text", "text": "CHEF-20 is implemented; both commands green."}]}})
    return rows


def test_the_main_sessions_stop_is_judged_once_the_process_has_ended(tmp_path, monkeypatch):
    from octryx_claude import hooks
    from octryx_claude.plain_driver import replay_stop
    from octryx_claude.platform import SessionContext
    from octryx_claude.state import LocalState

    state = LocalState(tmp_path / "home").ensure()
    key = "00000000-0000-4000-8000-0000000000dd"
    context = SessionContext("https://octryx.example.test", key, "ws", "", "")
    monkeypatch.setenv(hooks.DEFER_STOP_ENV, "1")
    assert hooks._defer_stop(state, context, {"hook_event_name": "Stop", "n": 1})
    assert not hooks._defer_stop(state, context, {"hook_event_name": "SubagentStop"})  # a child's end goes on
    seen = tmp_path / "seen.json"
    shim = tmp_path / "shim"
    shim.write_text(f"#!/bin/sh\necho \"$@ $OCTRYX_DEFER_STOP\" > {seen}.args\ncat > {seen}\n")
    shim.chmod(0o755)
    prepared = _prepared(tmp_path)
    prepared.env.update({"OCTRYX_CLAUDE_HOME": str(tmp_path / "home"), "OCTRYX_TEST_RUN_SHIM": str(shim)})
    replay_stop(prepared, str(tmp_path))
    assert json.loads(seen.read_text())["n"] == 1
    assert seen.with_suffix(".json.args").read_text().strip() == "hook stop 0"  # the replay is not deferred again
    assert not (state.session_dir(key) / hooks.DEFERRED_STOP_FILE).exists()


def test_a_stop_replay_the_platform_did_not_judge_runs_once_more_with_a_fresh_token(tmp_path, monkeypatch):
    from octryx_claude import hooks, plain_driver

    monkeypatch.setattr(plain_driver, "REPLAY_RETRY_SECONDS", 0)
    calls = tmp_path / "calls"
    script = ("#!/bin/sh\necho \"${OCTRYX_FORCE_TOKEN_REFRESH:-0}\" >> " + str(calls) + "\n"
              "if [ \"$OCTRYX_FORCE_TOKEN_REFRESH\" != 1 ]; then echo '{\"systemMessage\": \"Octryx verification gate "
              "unreachable (refused 401); stopping without verification.\"}'; fi\n")
    state, key, prepared = _replay_setup(tmp_path, monkeypatch, script)
    assert plain_driver.replay_stop(prepared, str(tmp_path)) is None  # the second attempt passed (no output)
    assert calls.read_text().split() == ["0", "1"]
    assert not (state.session_dir(key) / hooks.DEFERRED_STOP_FILE).exists()


def test_a_judged_stop_replay_is_not_repeated(tmp_path, monkeypatch):
    from octryx_claude import plain_driver

    monkeypatch.setattr(plain_driver, "REPLAY_RETRY_SECONDS", 0)
    calls = tmp_path / "calls"
    script = ("#!/bin/sh\necho x >> " + str(calls) + "\n"
              "echo '{\"decision\": \"block\", \"reason\": \"run the tests\"}'\n")
    _, _, prepared = _replay_setup(tmp_path, monkeypatch, script)
    assert plain_driver.replay_stop(prepared, str(tmp_path)) == {"decision": "block", "reason": "run the tests"}
    assert calls.read_text().split() == ["x"]


def test_the_stop_replay_judges_the_repository_the_job_runs_in_not_the_agents_last_folder(tmp_path, monkeypatch):
    import subprocess

    from octryx_claude import plain_driver
    from octryx_claude.contract_sizes import sizes
    from octryx_claude.run_contract import project_root

    monkeypatch.setattr(plain_driver, "REPLAY_RETRY_SECONDS", 0)
    seen = tmp_path / "project_dir"
    script = "#!/bin/sh\nprintf '%s' \"$CLAUDE_PROJECT_DIR\" > " + str(seen) + "\n"
    _, _, prepared = _replay_setup(tmp_path, monkeypatch, script)
    prepared.env.pop("CLAUDE_PROJECT_DIR", None)
    repo = tmp_path / "repo"
    repo.mkdir()
    plain_driver.replay_stop(prepared, str(repo))
    assert seen.read_text() == str(repo)

    # What the root decides: the changed file is counted (and so formatted) only from the repository's root.
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    (repo / "app" / "lib").mkdir(parents=True)
    (repo / "app" / "lib" / "a.dart").write_text("void main(){}\n")
    subprocess.run(["git", "-C", str(repo), "-c", "user.email=t@example.invalid", "-c", "user.name=t", "commit", "-q",
                    "--allow-empty", "-m", "base"], check=True)
    base = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True, text=True,
                          check=True).stdout.strip()
    monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
    assert sizes(project_root(str(repo / "app")), base)["files"] == {}  # before: the agent's cwd as the root
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(repo))
    assert list(sizes(project_root(str(repo / "app")), base)["files"]) == ["app/lib/a.dart"]


def test_the_stop_replay_logs_into_the_device_log(tmp_path, monkeypatch, caplog):
    import logging

    from octryx_claude import plain_driver

    monkeypatch.setattr(plain_driver, "REPLAY_RETRY_SECONDS", 0)
    assert plain_driver.logger.name.startswith("octryx_claude.device.")
    _, _, prepared = _replay_setup(tmp_path, monkeypatch, "#!/bin/sh\n")
    with caplog.at_level(logging.INFO, logger="octryx_claude.device"):
        plain_driver.replay_stop(prepared, str(tmp_path))
    assert any("stop replay: judged" in record.getMessage() for record in caplog.records)


def test_a_turn_that_only_waits_for_a_wakeup_ends_when_its_background_work_has(tmp_path, monkeypatch):
    import os
    import sys
    import time

    from octryx_claude import turn_idle

    monkeypatch.setattr(turn_idle, "GRACE_SECONDS", 0.3)
    monkeypatch.setattr(turn_idle, "POLL_SECONDS", 0.1)
    home = tmp_path / "home"
    prepared = _prepared(tmp_path)
    prepared.env["OCTRYX_CLAUDE_HOME"] = str(home)
    transcript = tmp_path / "session.jsonl"
    stop_file = home / "sessions" / prepared.session_key / "deferred_stop.json"
    fake = tmp_path / "claude"
    # The fake session writes its transcript and Stop, then waits like a pending 20-minute wakeup.
    fake.write_text(f"#!{sys.executable}\nimport json, os, time\nfrom pathlib import Path\n"
                    f"from tests.test_plain_driver_stop import _transcript_rows\n"
                    f"rows = _transcript_rows(time.time(), notified=os.environ.get('NOTIFIED') == '1')\n"
                    f"Path({str(transcript)!r}).write_text(''.join(json.dumps(r) + '\\n' for r in rows))\n"
                    f"time.sleep(0.5)\nstop = Path({str(stop_file)!r})\n"
                    f"stop.parent.mkdir(parents=True, exist_ok=True)\n"
                    f"stop.write_text(json.dumps({{'hook_event_name': 'Stop', "
                    f"'transcript_path': {str(transcript)!r}}}))\n"
                    f"time.sleep(float(os.environ.get('WAIT', '60')))\n")
    fake.chmod(0o755)
    prepared.cli_path = str(fake)
    prepared.env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1])
    events = []

    async def emit(event):
        events.append(event)

    async def turn(**env):
        prepared.env.update(env)
        return await PlainCliDriver().run_turn(prepared, cwd=str(tmp_path), prompt="CHEF-20", resume="cs-7", emit=emit)

    began = time.monotonic()
    result = asyncio.run(turn(NOTIFIED="1"))
    assert time.monotonic() - began < 15  # not the 60 s the session would have slept
    assert (result["status"], result["claude_session_id"]) == ("success", "cs-7")
    assert result["result_text"] == "CHEF-20 is implemented; both commands green."
    assert events[-1] == {"kind": "text", "text": "CHEF-20 is implemented; both commands green."}
    # Its background agent still running: the notice will wake the session, the process is left alone.
    began = time.monotonic()
    result = asyncio.run(turn(NOTIFIED="0", WAIT="3"))
    assert time.monotonic() - began >= 3 and result["status"] == "error"  # it exited on its own, printing nothing
    assert turn_idle.open_tasks(transcript, 0) == {"a9f49e228f6b2d0eb"}
    # A Stop older than the session's last message: it resumed (a notice or a wakeup's prompt arrived), not idle.
    at = time.time() - 100
    transcript.write_text("".join(json.dumps(row) + "\n" for row in _transcript_rows(at, notified=True)))
    os.utime(stop_file, (at + 0.35, at + 0.35))
    assert turn_idle.only_waiting(stop_file, at, time.time()) is None
    os.utime(stop_file, (at + 1, at + 1))
    assert turn_idle.only_waiting(stop_file, at, time.time()) == transcript


def test_a_stop_the_platform_blocks_after_the_process_continues_the_same_session_with_its_reason(tmp_path, monkeypatch):
    from octryx_claude import plain_driver

    fake = tmp_path / "claude"
    fake.write_text('#!/bin/sh\necho "$@" >> "$0.argv"\ncat >> "$0.stdin"\necho >> "$0.stdin"\n'
                    'echo \'{"type": "result", "is_error": false, "result": "all green", "session_id": "cs-7"}\'\n')
    fake.chmod(0o755)
    reason = "Code style: system_test/run_system_test.py grew from 585 to 657 lines (max 500) [tests_max_lines]"
    answers = [{"decision": "block", "reason": reason}, None]
    monkeypatch.setattr(plain_driver, "replay_stop", lambda _prepared, _cwd: answers.pop(0))
    events = []

    async def emit(event):
        events.append(event)

    result = asyncio.run(PlainCliDriver().run_turn(_prepared(tmp_path, cli=str(fake)), cwd=str(tmp_path),
                                                   prompt="Build S5.", resume=None, emit=emit))
    assert result["status"] == "success" and answers == []
    assert (tmp_path / "claude.stdin").read_text().splitlines() == ["Build S5.", reason]
    calls = (tmp_path / "claude.argv").read_text().splitlines()
    assert "--session-id" in calls[0] and "--resume cs-7" in calls[1]
    assert {"kind": "text", "text": f"Octryx: {reason}"} in events


def test_the_platform_stops_asking_after_the_continuation_cap(tmp_path, monkeypatch):
    from octryx_claude import plain_driver

    fake = tmp_path / "claude"
    fake.write_text('#!/bin/sh\necho x >> "$0.runs"\ncat > /dev/null\n'
                    'echo \'{"type": "result", "is_error": false, "result": "done", "session_id": "cs-8"}\'\n')
    fake.chmod(0o755)
    monkeypatch.setattr(plain_driver, "replay_stop", lambda _p, _c: {"decision": "block", "reason": "again"})

    async def emit(_event):
        return None

    asyncio.run(PlainCliDriver().run_turn(_prepared(tmp_path, cli=str(fake)), cwd=str(tmp_path), prompt="x",
                                          resume=None, emit=emit))
    assert len((tmp_path / "claude.runs").read_text().splitlines()) == plain_driver.MAX_STOP_CONTINUATIONS + 1
