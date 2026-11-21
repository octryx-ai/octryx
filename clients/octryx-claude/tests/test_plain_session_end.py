"""A plain run turn ends its session once, after its last process: a SessionEnd of the first ``claude -p`` process
would drop the seat credential the process resumed for the platform's blocked Stop still uses (401
``seat_credential_invalid``)."""

from __future__ import annotations

import asyncio
import io
import json
import os

import httpx

from octryx_claude import plain_driver, session_hooks
from octryx_claude.plain_driver import PlainCliDriver
from octryx_claude.plain_session import environment
from tests.plain_driver_support import _prepared

from .conftest import BASE_URL

KEY = "00000000-0000-4000-8000-0000000000dd"


def test_the_hook_only_remembers_the_session_end_of_a_plain_run_turn(state, monkeypatch):
    hook_input = {"hook_event_name": "SessionEnd", "reason": "other", "session_id": "cs-1", "cwd": "/w"}
    monkeypatch.setattr("sys.stdin", io.TextIOWrapper(io.BytesIO(json.dumps(hook_input).encode())))
    for name, value in (("OCTRYX_BASE_URL", BASE_URL), ("OCTRYX_SESSION_KEY", KEY), ("OCTRYX_WORKSPACE_ID", "ws-1"),
                        (session_hooks.DEFER_SESSION_END_ENV, "1")):
        monkeypatch.setenv(name, value)

    def finalize(_request):
        raise AssertionError("the session must not be finalized while the turn may go on")

    assert session_hooks.run_session_end(state, httpx.Client(transport=httpx.MockTransport(finalize))) == 0
    saved = state.session_dir(KEY) / session_hooks.DEFERRED_SESSION_END_FILE
    assert json.loads(saved.read_text()) == hook_input


def test_a_continued_turn_ends_its_session_once_after_its_last_process(tmp_path, monkeypatch):
    fake = tmp_path / "claude"
    fake.write_text('#!/bin/sh\ncat > /dev/null\necho "$OCTRYX_DEFER_SESSION_END" >> "$0.defer"\n'
                    'echo \'{"type": "result", "is_error": false, "result": "done", "session_id": "cs-7"}\'\n')
    fake.chmod(0o755)
    answers = [{"decision": "block", "reason": "Code style: wrap line 48"}, None]
    order: list[str] = []
    monkeypatch.setattr(plain_driver, "replay_stop", lambda _p, _c: order.append("stop") or answers.pop(0))
    monkeypatch.setattr(plain_driver, "replay_session_end", lambda _p, _c: order.append("end") or True)

    async def emit(_event):
        return None

    prepared = _prepared(tmp_path, cli=str(fake))
    assert environment(prepared)[session_hooks.DEFER_SESSION_END_ENV] == "1"
    asyncio.run(PlainCliDriver().run_turn(prepared, cwd=str(tmp_path), prompt="x", resume=None, emit=emit))
    assert order == ["stop", "stop", "end"]  # the session end after the continued process, never between
    assert (tmp_path / "claude.defer").read_text().split() == ["1", "1"]


def test_the_replayed_session_end_runs_the_launchers_hook_without_the_defer_flag(tmp_path):
    home = tmp_path / "home"
    shim = tmp_path / "octryx-claude"
    shim.write_text('#!/bin/sh\necho "$@" > "$0.args"\necho "${OCTRYX_DEFER_SESSION_END:-unset}" > "$0.defer"\n'
                    'cat > "$0.stdin"\n')
    shim.chmod(0o755)
    prepared = _prepared(tmp_path, hook_shim=str(shim))
    prepared.env.update({"OCTRYX_CLAUDE_HOME": str(home), session_hooks.DEFER_SESSION_END_ENV: "1"})
    folder = home / "sessions" / prepared.session_key
    folder.mkdir(parents=True)
    (folder / session_hooks.DEFERRED_SESSION_END_FILE).write_text('{"hook_event_name": "SessionEnd"}')
    assert plain_driver.replay_session_end(prepared, str(tmp_path)) is True
    assert (tmp_path / "octryx-claude.args").read_text().split() == ["hook", "session-end"]
    assert (tmp_path / "octryx-claude.defer").read_text().strip() == "unset"
    assert json.loads((tmp_path / "octryx-claude.stdin").read_text()) == {"hook_event_name": "SessionEnd"}
    assert not os.path.exists(folder / session_hooks.DEFERRED_SESSION_END_FILE)
    assert plain_driver.replay_session_end(prepared, str(tmp_path)) is False  # nothing left to replay
