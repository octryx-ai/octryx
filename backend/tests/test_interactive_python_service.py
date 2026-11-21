import asyncio
import json
from types import SimpleNamespace

import pytest

from app.services.interactive_python import interactive_python_manager


class _FakeWriter:
    def __init__(self, queue: asyncio.Queue[bytes]) -> None:
        self._queue = queue

    def write(self, data: bytes) -> None:
        payload = json.loads(data.decode("utf-8").strip())
        action = payload.get("action")
        response = {"id": payload.get("id"), "ok": True, "result": {}}
        if action == "exec_code":
            response["result"] = {"stdout": "ok\n", "stderr": "", "result": "42"}
        elif action == "list_variables":
            response["result"] = {"variable_count": 1, "variables": [{"name": "x", "type": "int", "repr": "42"}]}
        elif action == "close":
            response["result"] = {"closed": True}
        elif action == "fail":
            response = {
                "id": payload.get("id"),
                "ok": False,
                "error": {
                    "message": "Python action failed",
                    "error_code": "python_invalid_argument",
                    "retryable": False,
                },
            }
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
async def test_interactive_python_manager_exec_and_list(monkeypatch):
    async def _fake_spawn(**kwargs):
        return SimpleNamespace(process=_FakeProcess(), metadata={"provider": "host", "containerized": False})

    monkeypatch.setattr(
        "app.services.interactive_python.spawn_persistent_stdio_process",
        _fake_spawn,
    )
    monkeypatch.setattr("app.services.interactive_python.service._docker_available", lambda: True)

    exec_result = await interactive_python_manager.execute(
        python_session_id="session-1",
        workspace_root="/tmp",
        db=None,
        project_config={},
        action="exec_code",
        params={"code": "x = 42\nx"},
    )
    list_result = await interactive_python_manager.execute(
        python_session_id="session-1",
        workspace_root="/tmp",
        db=None,
        project_config={},
        action="list_variables",
        params={},
    )

    assert exec_result["python_session_id"] == "session-1"
    assert exec_result["result"] == "42"
    assert list_result["variables"][0]["name"] == "x"

    await interactive_python_manager.close("session-1")


@pytest.mark.asyncio
async def test_interactive_python_manager_close_kills_process_after_wait_timeout(monkeypatch):
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
        return SimpleNamespace(process=process, metadata={"provider": "host", "containerized": False})

    monkeypatch.setattr(
        "app.services.interactive_python.spawn_persistent_stdio_process",
        _fake_spawn,
    )
    monkeypatch.setattr("app.services.interactive_python.service._docker_available", lambda: True)

    exec_result = await interactive_python_manager.execute(
        python_session_id="session-timeout",
        workspace_root="/tmp",
        db=None,
        project_config={},
        action="exec_code",
        params={"code": "x = 1\nx"},
    )

    await interactive_python_manager.close(exec_result["python_session_id"])

    assert process.killed is True


@pytest.mark.asyncio
async def test_interactive_python_manager_surfaces_structured_error_contract(monkeypatch):
    async def _fake_spawn(**kwargs):
        return SimpleNamespace(process=_FakeProcess(), metadata={"provider": "host", "containerized": False})

    monkeypatch.setattr(
        "app.services.interactive_python.spawn_persistent_stdio_process",
        _fake_spawn,
    )
    monkeypatch.setattr("app.services.interactive_python.service._docker_available", lambda: True)

    with pytest.raises(RuntimeError) as exc_info:
        await interactive_python_manager.execute(
            python_session_id=None,
            workspace_root="/tmp",
            db=None,
            project_config={},
            action="fail",
            params={},
        )

    assert str(exc_info.value) == "Python action failed"
    assert getattr(exc_info.value, "error_code") == "python_invalid_argument"
    assert getattr(exc_info.value, "retryable") is False
