"""Persistent browser automation on top of the execution runtime."""

from __future__ import annotations

import asyncio
import json
import sys
import uuid
from dataclasses import dataclass, field
from importlib import import_module
from pathlib import Path
from typing import Any

from app.exceptions.contract import get_error_contract, with_error_contract

from ..persistent_process_runtime import (
    PersistentProcessHandle,
)
from ..persistent_process_runtime import (
    spawn_persistent_stdio_process as default_spawn_persistent_stdio_process,
)
from ..process_output_redaction import redact_process_output


@dataclass
class BrowserAutomationSession:
    id: str
    handle: PersistentProcessHandle
    workspace_root: Path
    execution_runtime: dict[str, Any] = field(default_factory=dict)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


class BrowserAutomationManager:
    def __init__(self) -> None:
        self._sessions: dict[str, BrowserAutomationSession] = {}

    def _workspace_root(self, workspace_root: str | None) -> Path:
        root = Path(workspace_root or Path.cwd()).resolve()
        root.mkdir(parents=True, exist_ok=True)
        return root

    async def _spawn(
        self,
        *,
        session_id: str | None,
        workspace_root: Path,
        db: Any | None,
        project_config: dict[str, Any] | None,
    ) -> BrowserAutomationSession:
        from . import spawn_persistent_stdio_process

        root_module = sys.modules.get("app.services.browser_automation")
        if root_module is None:
            root_module = import_module("app.services.browser_automation")
        root_spawn_process = getattr(
            root_module,
            "spawn_persistent_stdio_process",
            default_spawn_persistent_stdio_process,
        )
        spawn_process = spawn_persistent_stdio_process
        if (
            spawn_process is default_spawn_persistent_stdio_process
            and root_spawn_process is not default_spawn_persistent_stdio_process
        ):
            spawn_process = root_spawn_process

        session_id = str(session_id or uuid.uuid4())
        handle = await spawn_process(
            db=db,
            project_config=project_config,
            command=[sys.executable, "-m", "app.services.browser_runtime_entrypoint"],
            cwd=workspace_root,
            workspace_root=workspace_root,
            stderr_mode="pipe",
        )
        session = BrowserAutomationSession(
            id=session_id,
            handle=handle,
            workspace_root=workspace_root,
            execution_runtime=dict(handle.metadata),
        )
        self._sessions[session_id] = session
        return session

    async def _send_command(
        self,
        session: BrowserAutomationSession,
        *,
        action: str,
        params: dict[str, Any],
        timeout_sec: int = 45,
    ) -> dict[str, Any]:
        process = session.handle.process
        if process.stdin is None or process.stdout is None:
            raise with_error_contract(
                RuntimeError("Browser worker stdio is not available"),
                error_code="browser_transport_unavailable",
                retryable=True,
            )
        request_id = str(uuid.uuid4())
        payload = {"id": request_id, "action": action, "params": params}
        async with session.lock:
            process.stdin.write((json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8"))
            await process.stdin.drain()
            line = await asyncio.wait_for(process.stdout.readline(), timeout=timeout_sec)
        if not line:
            self._sessions.pop(session.id, None)
            raise with_error_contract(
                RuntimeError("Browser worker exited before sending a response"),
                error_code="browser_worker_exited",
                retryable=True,
            )
        response = json.loads(line.decode("utf-8", errors="replace"))
        if str(response.get("id") or "") != request_id:
            raise with_error_contract(
                RuntimeError("Browser worker returned an unexpected response id"),
                error_code="browser_protocol_error",
                retryable=False,
            )
        if not response.get("ok"):
            error_payload = response.get("error")
            message = "Browser worker request failed"
            if isinstance(error_payload, dict):
                message = str(error_payload.get("message") or message)
            elif error_payload:
                message = str(error_payload)
            # The worker's error text (a Playwright message) is what the agent acts on; it is kept,
            # but only through the process-output redactor (URLs it names can carry credentials).
            raise with_error_contract(
                RuntimeError(redact_process_output(message)),
                error_code=get_error_contract(error_payload).error_code if error_payload else "browser_worker_error",
                retryable=get_error_contract(error_payload).retryable if error_payload else False,
            )
        return response.get("result") if isinstance(response.get("result"), dict) else {"value": response.get("result")}

    async def execute(
        self,
        *,
        browser_session_id: str | None,
        workspace_root: str | None,
        db: Any | None,
        project_config: dict[str, Any] | None,
        action: str,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        params = dict(params or {})
        session = self._sessions.get(str(browser_session_id or "").strip())
        if session is None:
            session = await self._spawn(
                session_id=str(browser_session_id or "").strip() or None,
                workspace_root=self._workspace_root(workspace_root),
                db=db,
                project_config=project_config,
            )
        result = await self._send_command(session, action=action, params=params)
        payload = {
            "browser_session_id": session.id,
            "execution_runtime": dict(session.execution_runtime),
            **result,
        }
        if action == "close":
            await self.close(session.id)
        return payload

    async def close(self, browser_session_id: str) -> None:
        session = self._sessions.pop(browser_session_id, None)
        if session is None:
            return
        process = session.handle.process
        try:
            if process.returncode is None:
                process.terminate()
                await asyncio.wait_for(process.wait(), timeout=3)
        except TimeoutError:
            try:
                process.kill()
            except ProcessLookupError:
                pass
            except OSError:
                pass

    async def stop_all(self) -> None:
        for session_id in list(self._sessions.keys()):
            await self.close(session_id)


browser_automation_manager = BrowserAutomationManager()
