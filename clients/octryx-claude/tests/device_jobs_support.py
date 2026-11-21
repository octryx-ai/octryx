"""Shared helpers for the test_device_jobs_* modules."""

from __future__ import annotations

import asyncio
import types
from pathlib import Path

from octryx_claude import device_state
from octryx_claude.device_jobs import JobManager
from octryx_claude.device_session import PreparedSession, SessionRefusedError


class FakeChannel:
    def __init__(self) -> None:
        self.sent: list[tuple[str, str, dict]] = []
        self.paused = False

    async def send_job(self, job_id, message_type, body):
        self.sent.append((job_id, message_type, body))

    def of(self, message_type):
        return [body for _job, kind, body in self.sent if kind == message_type]


class FakeDriver:
    """Runs a scripted turn: optional tool decisions, then waits until released or interrupted."""

    def __init__(self, tools=(), hold: asyncio.Event | None = None) -> None:
        self.tools = list(tools)
        self.hold = hold
        self.interrupted = False
        self.calls: list[dict] = []
        self.verdicts: list[tuple[str, str]] = []

    async def run_turn(self, prepared, *, cwd, prompt, resume, decide, emit, fork=False):
        self.calls.append({"cwd": cwd, "prompt": prompt, "resume": resume, "env": prepared.env, "fork": fork})
        await emit({"kind": "text_delta", "text": "Working"})
        for tool, tool_input in self.tools:
            self.verdicts.append(await decide(tool, tool_input))
        if self.hold is not None:
            while not self.hold.is_set() and not self.interrupted:
                await asyncio.sleep(0.01)
        return {"status": "success", "result_text": "Done.", "claude_session_id": "cs-1", "cost_usd": 0.01}

    async def interrupt(self):
        self.interrupted = True

    async def disconnect(self):
        self.interrupted = True


class Prepare:
    def __init__(self, refuse: str = "") -> None:
        self.calls: list[dict] = []
        self.closed = 0
        self.refuse = refuse

    def __call__(self, state, **kwargs):
        self.calls.append(kwargs)
        if self.refuse:
            raise SessionRefusedError(self.refuse)
        test = self

        class Prepared(PreparedSession):
            def close(self) -> None:
                test.closed += 1

        return Prepared(session_key="00000000-0000-4000-8000-000000000001", cli_path="claude",
                        settings_path=Path("s.json"), mcp_path=Path("m.json"), env={"OCTRYX_CREDENTIAL_SET": "device"},
                        profile=kwargs["profile"])


class NoHttp:
    def __enter__(self):
        return None

    def __exit__(self, *exc):
        return None


def _manager(state, tmp_path, *, driver=None, prepare=None, folders=None, parallel=4, paused=False):
    repo = tmp_path / "repo"
    repo.mkdir(exist_ok=True)
    device_state.save_device(state, {"device_id": "dev_x", "name": "Box", "os": "linux",
                                     "base_url": "https://octryx.example.test", "folders": folders or [str(repo)],
                                     "max_parallel_jobs": parallel, "paused": paused})
    drivers = driver if isinstance(driver, list) else [driver or FakeDriver()]
    manager = JobManager(state, driver_factory=lambda: drivers.pop(0) if len(drivers) > 1 else drivers[0],
                         prepare=prepare or Prepare(), http_factory=NoHttp, shim=Path("/bin/true"))
    channel = FakeChannel()
    manager.attach(channel)
    return manager, channel, repo


def _offer(repo, job_id="dj_1", turn_id="t1", **extra):
    return {"job_id": job_id, "turn_id": turn_id, "prompt": "Run the tests", "folder": str(repo),
            "profile": "governed", "workspace_id": "ws-1", "limits": {"approval_timeout_s": 1}, **extra}


async def _settle(manager):
    for _ in range(200):
        if not manager.turns:
            return
        await asyncio.sleep(0.01)


# --- the SDK driver -------------------------------------------------------------------------------------------


def _fake_sdk():
    class Options:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    class Allow:
        def __init__(self, updated_input=None, updated_permissions=None):
            self.updated_input, self.updated_permissions = updated_input, updated_permissions

    class Deny:
        def __init__(self, message="", interrupt=False):
            self.message, self.interrupt = message, interrupt

    class Update:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    class Matcher:
        def __init__(self, matcher=None, hooks=None):
            self.matcher, self.hooks = matcher, hooks

    return types.SimpleNamespace(ClaudeAgentOptions=Options, PermissionResultAllow=Allow, PermissionResultDeny=Deny,
                                 PermissionUpdate=Update, HookMatcher=Matcher)
