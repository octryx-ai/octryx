"""Lightweight LSP (Language Server Protocol) client."""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any

from ..error_facts import error_text
from ..execution_runtime import ExecutionRuntimeUnavailableError
from ..persistent_process_runtime import spawn_persistent_stdio_process
from .protocol import (
    _LSP_SERVERS,
    PersistentProcessSpawner,
    WhichResolver,
    _encode_message,
    _lsp_error_text,
    _lsp_uri,
    _parse_messages,
)
from .queries import LspQueriesMixin

log = logging.getLogger(__name__)
root_log = logging.getLogger()

# A language server that does not answer shutdown quickly is terminated instead of holding up the platform's stop.
_SHUTDOWN_SECONDS = 2.0


def _log_warning(message: str, *args: object) -> None:
    log.warning(message, *args)
    if log.disabled or not log.propagate:
        root_log.warning(message, *args)


class LspClient(LspQueriesMixin):
    def __init__(
        self,
        language: str,
        workspace_root: str,
        *,
        db: Any | None = None,
        project_config: dict[str, Any] | None = None,
        which_resolver: WhichResolver = shutil.which,
        process_spawner: PersistentProcessSpawner = spawn_persistent_stdio_process,
    ) -> None:
        self.language = language
        self.workspace_root = str(Path(workspace_root).resolve())
        self._db = db
        self._project_config = project_config or {}
        self._which_resolver = which_resolver
        self._process_spawner = process_spawner
        self._proc: asyncio.subprocess.Process | None = None
        self._reader_task: asyncio.Task | None = None
        self._buf = b""
        self._pending: dict[int | str, asyncio.Future] = {}
        self._server_caps: dict = {}
        self._req_id = 0
        self.runtime_metadata: dict[str, Any] = {}

    async def start(self) -> bool:
        command = _LSP_SERVERS.get(self.language)
        if not command:
            return False

        binary = command[0]
        if not self._which_resolver(binary):
            if self.language in {"typescript", "javascript"} and self._which_resolver("npx"):
                command = ["npx", "--yes"] + command
            else:
                log.warning("LSP binary not found: %s", binary)
                return False

        try:
            handle = await self._process_spawner(
                db=self._db,
                project_config=self._project_config,
                command=[str(part) for part in command],
                cwd=Path(self.workspace_root),
                workspace_root=Path(self.workspace_root),
                stderr_mode="devnull",
            )
            self._proc = handle.process
            self.runtime_metadata = dict(handle.metadata)
        except (ExecutionRuntimeUnavailableError, OSError, ValueError) as exc:
            _log_warning("Failed to start LSP server %s: %s", command[0], error_text("lsp_start_failed", exc))
            return False

        self._reader_task = asyncio.create_task(self._read_loop())

        init_result = await self._request(
            "initialize",
            {
                "processId": os.getpid(),
                "rootUri": _lsp_uri(self.workspace_root),
                "capabilities": {
                    "textDocument": {
                        "definition": {"linkSupport": False},
                        "references": {},
                        "hover": {},
                        "documentSymbol": {"hierarchicalDocumentSymbolSupport": False},
                        "publishDiagnostics": {},
                    },
                    "workspace": {
                        "symbol": {},
                    },
                },
                "initializationOptions": None,
            },
        )
        self._server_caps = (init_result or {}).get("capabilities", {})
        await self._notify("initialized", {})
        return True

    async def stop(self) -> None:
        try:
            await self._request("shutdown", {}, timeout=_SHUTDOWN_SECONDS)
        except Exception:
            pass
        try:
            await self._notify("exit", {})
        except Exception:
            pass
        if self._reader_task:
            self._reader_task.cancel()
        if self._proc and self._proc.returncode is None:
            try:
                self._proc.terminate()
                await asyncio.wait_for(self._proc.wait(), timeout=3)
            except TimeoutError:
                self._proc.kill()
            except Exception:
                pass

    async def _read_loop(self) -> None:
        if not self._proc or not self._proc.stdout:
            return
        while True:
            try:
                chunk = await self._proc.stdout.read(4096)
            except Exception:
                break
            if not chunk:
                break
            self._buf += chunk
            messages, self._buf = _parse_messages(self._buf)
            for msg in messages:
                msg_id = msg.get("id")
                if msg_id is not None and msg_id in self._pending:
                    future = self._pending.pop(msg_id)
                    if not future.done():
                        if "error" in msg:
                            future.set_exception(RuntimeError(_lsp_error_text(msg["error"])))
                        else:
                            future.set_result(msg.get("result"))

    def _next_id(self) -> int:
        self._req_id += 1
        return self._req_id

    async def _send(self, msg: dict) -> None:
        if not self._proc or not self._proc.stdin:
            raise RuntimeError("LSP server not running")
        self._proc.stdin.write(_encode_message(msg))
        await self._proc.stdin.drain()

    async def _request(self, method: str, params: Any, timeout: float = 15.0) -> Any:
        req_id = self._next_id()
        future: asyncio.Future = asyncio.get_event_loop().create_future()
        self._pending[req_id] = future
        await self._send({"jsonrpc": "2.0", "id": req_id, "method": method, "params": params})
        try:
            return await asyncio.wait_for(future, timeout=timeout)
        except TimeoutError:
            self._pending.pop(req_id, None)
            return None

    async def _notify(self, method: str, params: Any) -> None:
        await self._send({"jsonrpc": "2.0", "method": method, "params": params})


class LspClientManager:
    def __init__(
        self,
        *,
        client_factory: Callable[..., LspClient] = LspClient,
    ) -> None:
        self._client_factory = client_factory
        self._clients: dict[tuple[str, str], LspClient] = {}

    async def get_or_create(
        self,
        language: str,
        workspace_root: str,
        *,
        db: Any | None = None,
        project_config: dict[str, Any] | None = None,
    ) -> LspClient | None:
        key = (language, workspace_root)
        client = self._clients.get(key)
        if client and client._proc and client._proc.returncode is None:
            return client
        client = self._client_factory(language, workspace_root, db=db, project_config=project_config)
        started = await client.start()
        if not started:
            return None
        self._clients[key] = client
        return client

    async def stop_all(self) -> None:
        # Side by side: a shutdown waits for every server at most once, however many are open.
        await asyncio.gather(*(client.stop() for client in self._clients.values()), return_exceptions=True)
        self._clients.clear()


__all__ = [
    "LspClient",
    "LspClientManager",
]
