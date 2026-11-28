import asyncio
import json
from types import SimpleNamespace

import pytest

from app.services import browser_automation as browser_automation_package
from app.services.browser_automation import browser_automation_manager


class _FakeWriter:
    def __init__(self, queue: asyncio.Queue[bytes]) -> None:
        self._queue = queue
        self._last_payload: dict | None = None

    def write(self, data: bytes) -> None:
        self._last_payload = json.loads(data.decode("utf-8").strip())
        action = self._last_payload.get("action")
        response = {"id": self._last_payload.get("id"), "ok": True, "result": {}}
        if action == "open_url":
            response["result"] = {"opened": True, "url": self._last_payload["params"]["url"], "title": "Acme Orders"}
        elif action == "snapshot":
            response["result"] = {
                "url": "https://example.test",
                "title": "Acme Orders",
                "element_count": 1,
                "elements": [{"ref": "e1", "tag": "button", "text": "Login"}],
            }
        elif action == "close":
            response["result"] = {"closed": True}
        elif action == "fail":
            response = {
                "id": self._last_payload.get("id"),
                "ok": False,
                "error": {
                    "message": "Browser action failed",
                    "error_code": "browser_invalid_argument",
                    "retryable": False,
                },
            }
        else:
            response["result"] = {"action": action}
        self._queue.put_nowait((json.dumps(response) + "\n").encode("utf-8"))

    async def drain(self) -> None:
        return None


class _FakeReader:
    def __init__(self, queue: asyncio.Queue[bytes]) -> None:
        self._queue = queue

    async def readline(self) -> bytes:
        return await self._queue.get()


class _FakeProcess:
    def __init__(self) -> None:
        self._queue: asyncio.Queue[bytes] = asyncio.Queue()
        self.stdin = _FakeWriter(self._queue)
        self.stdout = _FakeReader(self._queue)
        self.returncode = None

    def terminate(self) -> None:
        self.returncode = 0

    async def wait(self) -> int:
        self.returncode = 0
        return 0

    def kill(self) -> None:
        self.returncode = -9


@pytest.mark.asyncio
async def test_browser_automation_manager_reuses_session(monkeypatch):
    async def _fake_spawn(**kwargs):
        return SimpleNamespace(process=_FakeProcess(), metadata={"provider": "host", "containerized": False})

    monkeypatch.setattr(browser_automation_package, "spawn_persistent_stdio_process", _fake_spawn)

    open_result = await browser_automation_manager.execute(
        browser_session_id=None,
        workspace_root="/tmp",
        db=None,
        project_config={},
        action="open_url",
        params={"url": "https://example.test"},
    )
    snapshot_result = await browser_automation_manager.execute(
        browser_session_id=open_result["browser_session_id"],
        workspace_root="/tmp",
        db=None,
        project_config={},
        action="snapshot",
        params={},
    )

    assert open_result["opened"] is True
    assert snapshot_result["browser_session_id"] == open_result["browser_session_id"]
    assert snapshot_result["elements"][0]["ref"] == "e1"

    await browser_automation_manager.close(open_result["browser_session_id"])


@pytest.mark.asyncio
async def test_browser_automation_manager_close_removes_session(monkeypatch):
    async def _fake_spawn(**kwargs):
        return SimpleNamespace(process=_FakeProcess(), metadata={"provider": "docker", "containerized": True})

    monkeypatch.setattr(browser_automation_package, "spawn_persistent_stdio_process", _fake_spawn)

    open_result = await browser_automation_manager.execute(
        browser_session_id=None,
        workspace_root="/tmp",
        db=None,
        project_config={},
        action="open_url",
        params={"url": "https://example.test"},
    )
    close_result = await browser_automation_manager.execute(
        browser_session_id=open_result["browser_session_id"],
        workspace_root="/tmp",
        db=None,
        project_config={},
        action="close",
        params={},
    )

    assert close_result["closed"] is True
    assert open_result["browser_session_id"] not in browser_automation_manager._sessions


@pytest.mark.asyncio
async def test_browser_automation_manager_close_kills_process_after_wait_timeout(monkeypatch):
    class _SlowProcess(_FakeProcess):
        def __init__(self) -> None:
            super().__init__()
            self.killed = False

        async def wait(self) -> int:
            await asyncio.sleep(3600)
            return 0

        def kill(self) -> None:
            self.killed = True
            super().kill()

    process = _SlowProcess()

    async def _fake_spawn(**kwargs):
        return SimpleNamespace(process=process, metadata={"provider": "docker", "containerized": True})

    monkeypatch.setattr(browser_automation_package, "spawn_persistent_stdio_process", _fake_spawn)

    open_result = await browser_automation_manager.execute(
        browser_session_id=None,
        workspace_root="/tmp",
        db=None,
        project_config={},
        action="open_url",
        params={"url": "https://example.test"},
    )

    await browser_automation_manager.close(open_result["browser_session_id"])

    assert process.killed is True


@pytest.mark.asyncio
async def test_browser_automation_manager_surfaces_structured_error_contract(monkeypatch):
    async def _fake_spawn(**kwargs):
        return SimpleNamespace(process=_FakeProcess(), metadata={"provider": "host", "containerized": False})

    monkeypatch.setattr(browser_automation_package, "spawn_persistent_stdio_process", _fake_spawn)

    with pytest.raises(RuntimeError) as exc_info:
        await browser_automation_manager.execute(
            browser_session_id=None,
            workspace_root="/tmp",
            db=None,
            project_config={},
            action="fail",
            params={},
        )

    assert str(exc_info.value) == "Browser action failed"
    assert getattr(exc_info.value, "error_code") == "browser_invalid_argument"
    assert getattr(exc_info.value, "retryable") is False
