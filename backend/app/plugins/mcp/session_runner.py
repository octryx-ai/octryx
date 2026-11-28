"""One live MCP client connection, held open by its own task."""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from typing import Any

STOP_TIMEOUT_SECONDS = 10.0


class McpSessionRunner:
    def __init__(
        self,
        name: str,
        open_streams: Callable[[], AbstractAsyncContextManager[Any]],
        session_factory: Callable[[Any, Any], Any],
    ) -> None:
        self.name = name
        self._open_streams = open_streams
        self._session_factory = session_factory
        self._ready = asyncio.Event()
        self._stop = asyncio.Event()
        self._task: asyncio.Task[None] | None = None
        self._error: BaseException | None = None
        self.session: Any = None

    async def start(self, timeout: float) -> Any:
        self._task = asyncio.create_task(self._run(), name=f"mcp-session:{self.name}")
        try:
            await asyncio.wait_for(self._ready.wait(), timeout=timeout)
        except TimeoutError:
            await self._cancel()
            raise
        if self._error is not None:
            await self._cancel()
            raise self._error
        return self.session

    async def _run(self) -> None:
        try:
            async with self._open_streams() as streams:
                read, write = streams[0], streams[1]
                async with self._session_factory(read, write) as session:
                    await session.initialize()
                    self.session = session
                    self._ready.set()
                    await self._stop.wait()
        except asyncio.CancelledError:
            raise
        except BaseException as exc:  # noqa: BLE001 - handed to start(); a task must not die silently
            if not self._ready.is_set():
                self._error = exc
        finally:
            self.session = None
            self._ready.set()

    async def stop(self) -> None:
        self._stop.set()
        task = self._task
        if task is None or task.done():
            return
        try:
            await asyncio.wait_for(asyncio.shield(task), timeout=STOP_TIMEOUT_SECONDS)
        except (TimeoutError, Exception):
            await self._cancel()

    async def _cancel(self) -> None:
        task = self._task
        if task is None or task.done():
            return
        task.cancel()
        with contextlib.suppress(BaseException):
            await task

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done() and self.session is not None


__all__ = ["McpSessionRunner", "STOP_TIMEOUT_SECONDS"]
