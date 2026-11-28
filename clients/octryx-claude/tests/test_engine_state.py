"""A session's engine files travel with the platform: packed after a turn, restored on another runner (or on a device
that lost them) before the engine resumes the same session."""

from __future__ import annotations

import hashlib
import io
import json
import tarfile
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from octryx_claude import codex_driver, engine_state, plain_driver, runner
from octryx_claude.device_session import PreparedSession
from octryx_claude.state import LocalState
from tests.codex_appserver_fake import calls, fake_appserver
from tests.codex_driver_support import _stop_replay
from tests.device_jobs_support import FakeDriver, _manager, _offer, _settle

ROLLOUT = "2026/11/26/rollout-2026-11-26T10-00-00-th-42.jsonl"


# The platform's two session-state routes: one snapshot per thread.
class Platform:
    def __init__(self) -> None:
        self.snapshot: bytes | None = None
        self.puts: list[dict] = []

    def __call__(self):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return None

    def put(self, url, *, params, content, headers):
        self.puts.append(dict(params))
        if hashlib.sha256(content).hexdigest() != params["sha256"]:
            return SimpleNamespace(status_code=400, content=b"")
        self.snapshot = content
        return SimpleNamespace(status_code=200, content=b"")

    def get(self, url, *, headers):
        if self.snapshot is None:
            return SimpleNamespace(status_code=404, content=b"")
        return SimpleNamespace(status_code=200, content=self.snapshot)

    def offered(self) -> dict:
        last = self.puts[-1]
        return {"sha256": last["sha256"], "engine": last["engine"], "engine_session_id": last["engine_session_id"]}


@pytest.fixture
def platform(monkeypatch):
    fake = Platform()
    monkeypatch.setattr(engine_state, "_client", fake)
    monkeypatch.setattr(engine_state, "_token", lambda state: "device-token")
    return fake


def _claude_session(config: Path, cwd: Path, session="cs-1", main=b'{"n":1}\n') -> Path:
    project = config / "projects" / engine_state.project_slug(str(cwd))
    (project / session / "subagents").mkdir(parents=True)
    (project / f"{session}.jsonl").write_bytes(main)
    (project / session / "subagents" / "agent-a1.jsonl").write_bytes(b'{"sub":1}\n')
    return project


def test_claude_files_pack_reproducibly_and_restore_under_another_working_directory(tmp_path):
    first = _claude_session(tmp_path / "a" / "claude-config", tmp_path / "work-a")
    files = engine_state.claude_files(tmp_path / "a" / "claude-config", str(tmp_path / "work-a"), "cs-1")
    assert sorted(files) == ["claude/cs-1.jsonl", "claude/cs-1/subagents/agent-a1.jsonl"]
    packed = engine_state.pack(files)
    time.sleep(0.01)
    (first / "cs-1.jsonl").touch()
    assert engine_state.pack(files) == packed  # no times, owners or modes of this device

    target = tmp_path / "b" / "claude-config" / "projects" / engine_state.project_slug(str(tmp_path / "work-b"))
    assert engine_state.unpack(packed, "cs-1", project=target) == 2
    assert (target / "cs-1.jsonl").read_bytes() == b'{"n":1}\n'
    assert (target / "cs-1" / "subagents" / "agent-a1.jsonl").read_bytes() == b'{"sub":1}\n'


def test_a_codex_rollout_round_trips_into_the_threads_folder(tmp_path):
    rollout = tmp_path / "a" / ROLLOUT
    rollout.parent.mkdir(parents=True)
    rollout.write_bytes(b'{"type":"session_meta"}\n')
    files = engine_state.codex_files(tmp_path / "a", "th-42")
    assert list(files) == [f"codex/{ROLLOUT}"]
    assert engine_state.unpack(engine_state.pack(files), "th-42", threads=tmp_path / "b") == 1
    assert (tmp_path / "b" / ROLLOUT).read_bytes() == b'{"type":"session_meta"}\n'


def test_only_the_sessions_own_files_are_written_and_a_longer_local_copy_stays(tmp_path):
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        for name in ("claude/../../escape.jsonl", "claude/cs-2.jsonl", "codex/x/rollout-1-th-42.jsonl",
                     "claude/cs-1.jsonl"):
            info = tarfile.TarInfo(name)
            info.size = 7
            archive.addfile(info, io.BytesIO(b"older\n\n"))
    project = tmp_path / "project"
    project.mkdir()
    (project / "cs-1.jsonl").write_bytes(b"older\n\nand the turn after\n")
    assert engine_state.unpack(buffer.getvalue(), "cs-1", project=project, threads=tmp_path / "threads") == 0
    assert (project / "cs-1.jsonl").read_bytes() == b"older\n\nand the turn after\n"
    assert sorted(path.name for path in tmp_path.rglob("*") if path.is_file()) == ["cs-1.jsonl"]
    (project / "cs-1.jsonl").write_bytes(b"old")  # a stale copy: the platform's longer one replaces it
    assert engine_state.unpack(buffer.getvalue(), "cs-1", project=project) == 1


# Claude Code as far as its files go: resume reads ``<id>.jsonl`` under the working directory's folder.
class TranscriptDriver(FakeDriver):
    def __init__(self, line: bytes) -> None:
        super().__init__()
        self.line, self.seen = line, None

    async def run_turn(self, prepared, *, cwd, prompt, resume, decide, emit, fork=False):
        result = await super().run_turn(prepared, cwd=cwd, prompt=prompt, resume=resume, decide=decide, emit=emit,
                                        fork=fork)
        project = Path(prepared.env["CLAUDE_CONFIG_DIR"]) / "projects" / engine_state.project_slug(cwd)
        main = project / f"{result['claude_session_id']}.jsonl"
        self.seen = main.read_bytes() if resume and main.exists() else None
        if resume and self.seen is None:
            return {"status": "error", "error": "no_conversation_found"}
        project.mkdir(parents=True, exist_ok=True)
        with main.open("ab") as handle:
            handle.write(self.line)
        return result


def _prepare(state: LocalState):
    def prepare(_state, **kwargs):
        return PreparedSession(session_key="00000000-0000-4000-8000-000000000001", cli_path="claude",
                               settings_path=Path("s.json"), mcp_path=Path("m.json"),
                               env={"CLAUDE_CONFIG_DIR": str(state.root / "claude-config")}, profile=kwargs["profile"])

    return prepare


async def _turn(state, tmp_path, driver, **offer):
    manager, channel, repo = _manager(state, tmp_path, driver=driver, prepare=_prepare(state))
    await manager.handle("job_offer", _offer(repo, **offer))
    await _settle(manager)
    return channel, repo


def _runner(tmp_path: Path, name: str) -> tuple[LocalState, Path]:
    home = tmp_path / name
    return LocalState(home / "state").ensure(), home


@pytest.mark.asyncio
async def test_claude_continues_on_another_runner_and_on_a_device_that_lost_its_files(tmp_path, platform):
    state_a, home_a = _runner(tmp_path, "runner-a")
    first = TranscriptDriver(b'{"turn":1}\n')
    channel, _repo = await _turn(state_a, home_a, first)
    assert channel.of("turn_finished")[0]["status"] == "success" and platform.puts[-1]["engine"] == "claude_code"
    # Runner A takes another person's turn: everything of the first one is wiped.
    assert runner.admit_tenant(state_a, {"owner_user_id": "p2", "workspace_id": "w"}, busy=False,
                               roots=[state_a.root / "claude-config"])
    assert not any((state_a.root / "claude-config").iterdir())

    state_b, home_b = _runner(tmp_path, "runner-b")
    offer = {"resume_session_id": "cs-1", "session_state": platform.offered(), "owner_user_id": "p1",
             "workspace_id": "w"}
    assert runner.admit_tenant(state_b, offer, busy=False, roots=[home_b / "empty"])
    assert offer["resume_session_id"] == "cs-1"  # kept: its files come from the platform
    second = TranscriptDriver(b'{"turn":2}\n')
    channel, _repo = await _turn(state_b, home_b, second, turn_id="t2", **offer)
    assert second.calls[0]["resume"] == "cs-1" and second.seen == b'{"turn":1}\n'
    assert channel.of("turn_finished")[0]["status"] == "success"

    # Runner A gets the session back without its files (and a stale copy would be replaced the same way).
    third = TranscriptDriver(b'{"turn":3}\n')
    await _turn(state_a, home_a, third, turn_id="t3", resume_session_id="cs-1", session_state=platform.offered())
    assert third.seen == b'{"turn":1}\n{"turn":2}\n'


@pytest.mark.asyncio
async def test_without_the_platforms_files_the_turn_starts_fresh(tmp_path, platform):
    state, home = _runner(tmp_path, "runner")
    driver = TranscriptDriver(b'{"turn":1}\n')
    state_offer = {"sha256": "0" * 64, "engine": "claude_code", "engine_session_id": "cs-1"}
    channel, _repo = await _turn(state, home, driver, resume_session_id="cs-1", session_state=state_offer)
    assert driver.calls[0]["resume"] is None and channel.of("turn_finished")[0]["status"] == "success"
    assert runner.admit_tenant(state, {"owner_user_id": "p", "resume_session_id": "cs-1"}, busy=False, roots=[]) \
        is True  # the same tenant keeps whatever it has


@pytest.mark.asyncio
async def test_codex_resumes_its_thread_on_another_runner_from_the_platform(tmp_path, platform, monkeypatch):
    monkeypatch.setattr(plain_driver, "judged_stop", _stop_replay((None, True)))
    monkeypatch.setattr(codex_driver, "MCP_READY_POLL_SECONDS", 0.01)
    answer = [{"notify": "item/completed", "params": {"item": {"id": "m1", "type": "agentMessage", "text": "Done."}}}]
    codex = fake_appserver(tmp_path / "bin", thread="th-42", turns=[answer, answer])
    offer = {"engine": "codex", "folder": str(tmp_path), "profile": "governed"}

    def prepared(home: Path):
        session = home / "sessions" / "k1"
        session.mkdir(parents=True, exist_ok=True)
        return SimpleNamespace(
            session_key="k1", model="team-coder", profile="governed", settings_path=session / "settings.json",
            env={"PATH": "/usr/bin:/bin", "OCTRYX_SESSION_KEY": "k1", "OCTRYX_WORKSPACE_ID": "w1",
                 "OCTRYX_CLAUDE_HOME": str(home)},
            extra={"gateway": {"base_url": "https://platform.test", "session_key": "k1", "workspace_id": "w1"},
                   "hook_shim": "/opt/octryx/bin/octryx-claude", "permission_mode": "bypassPermissions"})

    async def emit(event):
        return None

    state_a, home_a = _runner(tmp_path, "runner-a")
    rollout = home_a / "codex-threads" / ROLLOUT
    rollout.parent.mkdir(parents=True)
    rollout.write_bytes(b'{"type":"session_meta","id":"th-42"}\n')
    first = await codex_driver.CodexDriver(str(codex)).run_turn(prepared(home_a), cwd=str(tmp_path), prompt="p",
                                                                 resume=None, emit=emit)
    await engine_state.after_turn(state_a, prepared(home_a), offer, first, job_id="dj_1", turn_id="t1")
    assert first["claude_session_id"] == "th-42" and platform.puts[-1]["engine"] == "codex"

    state_b, home_b = _runner(tmp_path, "runner-b")
    turn = {**offer, "resume": "th-42", "session_state": platform.offered()}
    await engine_state.before_turn(state_b, prepared(home_b), turn, job_id="dj_2")
    assert (home_b / "codex-threads" / ROLLOUT).read_bytes() == rollout.read_bytes()
    await codex_driver.CodexDriver(str(codex)).run_turn(prepared(home_b), cwd=str(tmp_path), prompt="p",
                                                        resume=turn["resume"], emit=emit)
    resumed = [call["params"] for call in calls(tmp_path / "bin") if call.get("method") == "thread/resume"]
    assert [params["threadId"] for params in resumed] == ["th-42"]
    assert json.loads((home_b / "sessions" / "k1" / "codex-home" / "sessions" / ROLLOUT).read_text())["id"] == "th-42"
