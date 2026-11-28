"""JSON-RPC client for ``codex app-server`` over stdio."""

from __future__ import annotations

import asyncio
import contextlib
import itertools
import json
import os
from collections import deque
from collections.abc import Awaitable, Callable
from typing import Any

STREAM_LIMIT = 16 * 1024 * 1024
TERMINATE_GRACE = 10.0
KILL_WAIT = 5.0
REQUEST_TIMEOUT = 120.0
MAX_NOTIFICATIONS = 10_000
MAX_NOTIFICATION_BYTES = 32 * 1024 * 1024
MAX_SERVER_REQUESTS = 32
EXITED = "octryx/exited"

ServerRequestHandler = Callable[[str, dict[str, Any]], Awaitable[dict[str, Any]]]


class AppServerError(Exception):
    def __init__(self, method: str, code: str) -> None:
        super().__init__(f"{method}: {code}")
        self.method = method
        self.code = code


class UnknownServerRequestError(Exception):
    pass


def _rpc_code(error: Any) -> str:
    code = error.get("code") if isinstance(error, dict) else None
    return f"rpc_{code}" if isinstance(code, int) and not isinstance(code, bool) else "rpc_invalid"


class AppServerClient:
    def __init__(self, argv: list[str], *, env: dict[str, str], cwd: str, on_request: ServerRequestHandler) -> None:
        self._argv = argv
        self._env = env
        self._cwd = cwd
        self._on_request = on_request
        self._ids = itertools.count(1)
        self._pending: dict[int, asyncio.Future[dict[str, Any]]] = {}
        self._process: asyncio.subprocess.Process | None = None
        self._reader: asyncio.Task[Any] | None = None
        self._answers: set[asyncio.Task[Any]] = set()
        self._closed = False
        self._fatal = False
        self._queued: deque[tuple[int, dict[str, Any]]] = deque()
        self._queued_bytes = 0
        self._arrived = asyncio.Event()

    @property
    def running(self) -> bool:
        return not self._closed and self._process is not None and self._process.returncode is None

    async def start(self) -> dict[str, Any]:
        self._process = await asyncio.create_subprocess_exec(
            *self._argv, cwd=self._cwd, env=self._env, stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL, limit=STREAM_LIMIT)
        self._reader = asyncio.create_task(self._read())
        info = await self.request("initialize", {"clientInfo": {"name": "octryx", "version": "1"}})
        try:
            await asyncio.wait_for(self._send({"jsonrpc": "2.0", "method": "initialized"}), REQUEST_TIMEOUT)
        except TimeoutError:
            raise AppServerError("initialized", "timeout") from None
        return info

    async def next_notification(self) -> dict[str, Any]:
        # A failed transport is reported at once; an ordinary end only after what came before it.
        while True:
            if self._fatal:
                return {"method": EXITED}
            if self._queued:
                size, message = self._queued.popleft()
                self._queued_bytes -= size
                return message
            if self._closed:
                return {"method": EXITED}
            self._arrived.clear()
            await self._arrived.wait()

    async def request(self, method: str, params: dict[str, Any], timeout: float = REQUEST_TIMEOUT) -> dict[str, Any]:
        request_id = next(self._ids)
        try:
            reply = await asyncio.wait_for(self._roundtrip(request_id, method, params), timeout)
        except TimeoutError:
            raise AppServerError(method, "timeout") from None
        finally:
            self._pending.pop(request_id, None)
        if "error" in reply:
            raise AppServerError(method, _rpc_code(reply["error"]))
        result = reply.get("result")
        return result if isinstance(result, dict) else {}

    async def _roundtrip(self, request_id: int, method: str, params: dict[str, Any]) -> dict[str, Any]:
        future: asyncio.Future[dict[str, Any]] = asyncio.get_running_loop().create_future()
        self._pending[request_id] = future
        await self._send({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params})
        return await future

    async def close(self) -> None:
        self._end()
        process = self._process
        if process is not None and process.returncode is None:
            with contextlib.suppress(OSError, AttributeError):
                process.stdin.close()  # type: ignore[union-attr]
            try:
                await asyncio.wait_for(process.wait(), TERMINATE_GRACE)
            except TimeoutError:
                with contextlib.suppress(ProcessLookupError):
                    os.kill(process.pid, 9)
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(process.wait(), KILL_WAIT)
        tasks = [*self._answers, *([self._reader] if self._reader is not None else [])]
        for task in tasks:
            task.cancel()

    def _end(self, *, fatal: bool = False) -> None:
        self._fatal = self._fatal or fatal
        if self._closed:
            self._arrived.set()
            return
        self._closed = True
        for future in self._pending.values():
            if not future.done():
                future.set_exception(AppServerError("transport", "closed"))
        self._arrived.set()

    async def _send(self, message: dict[str, Any]) -> None:
        if not self.running:
            raise AppServerError(str(message.get("method") or "reply"), "not_running")
        assert self._process is not None and self._process.stdin is not None
        self._process.stdin.write((json.dumps(message) + "\n").encode())
        try:
            await self._process.stdin.drain()
        except (BrokenPipeError, ConnectionResetError):
            self._end()
            raise AppServerError(str(message.get("method") or "reply"), "not_running") from None

    async def _read(self) -> None:
        assert self._process is not None and self._process.stdout is not None
        fatal = False
        try:
            async for line in self._process.stdout:
                if not self._dispatch(line):
                    fatal = True
                    break
        except (ValueError, asyncio.LimitOverrunError, OSError):
            fatal = True
        finally:
            self._end(fatal=fatal)

    def _dispatch(self, line: bytes) -> bool:
        try:
            message = json.loads(line)
        except ValueError:
            return True
        if not isinstance(message, dict) or not isinstance(message.get("params", {}), dict):
            return True
        method, message_id = message.get("method"), message.get("id")
        if isinstance(method, str) and isinstance(message_id, (int, str)) and not isinstance(message_id, bool):
            if len(self._answers) >= MAX_SERVER_REQUESTS:
                return False
            task = asyncio.create_task(self._answer(message))
            self._answers.add(task)
            task.add_done_callback(self._answers.discard)
        elif isinstance(message_id, int) and not isinstance(message_id, bool) and method is None:
            future = self._pending.get(message_id)
            if future is not None and not future.done():
                future.set_result(message)
        elif isinstance(method, str) and message_id is None:
            if (len(self._queued) >= MAX_NOTIFICATIONS
                    or self._queued_bytes + len(line) > MAX_NOTIFICATION_BYTES):
                return False
            self._queued.append((len(line), message))
            self._queued_bytes += len(line)
            self._arrived.set()
        return True

    async def _answer(self, message: dict[str, Any]) -> None:
        try:
            result = await self._on_request(str(message["method"]), message.get("params") or {})
        except UnknownServerRequestError:
            await self._reply(message["id"], error=(-32601, "unsupported"))
        except Exception:  # noqa: BLE001 - an unanswered request would hang the turn
            await self._reply(message["id"], error=(-32603, "request failed"))
        else:
            await self._reply(message["id"], result=result)

    async def _reply(self, message_id: Any, *, result: dict[str, Any] | None = None,
                     error: tuple[int, str] | None = None) -> None:
        reply: dict[str, Any] = {"jsonrpc": "2.0", "id": message_id}
        if error is not None:
            reply["error"] = {"code": error[0], "message": error[1]}
        else:
            reply["result"] = result or {}
        with contextlib.suppress(AppServerError, TimeoutError):
            await asyncio.wait_for(self._send(reply), REQUEST_TIMEOUT)


__all__ = ["EXITED", "AppServerClient", "AppServerError", "UnknownServerRequestError"]
