"""Persistent interactive Python runtime on top of the execution runtime."""

from __future__ import annotations

import asyncio
import json
import shutil
import sys
import uuid
from dataclasses import dataclass, field
from importlib import import_module
from pathlib import Path
from typing import Any

from app.exceptions.contract import get_error_contract, with_error_contract

from ..persistent_process_runtime import PersistentProcessHandle
from ..persistent_process_runtime import (
    spawn_persistent_stdio_process as default_spawn_persistent_stdio_process,
)
from ..process_output_redaction import redact_process_output

# The cell output the agent reads; each is kept, but only through the process-output redactor.
_CELL_OUTPUT_KEYS = ("stdout", "stderr", "result")

# Interactive Python executes user-supplied code — Docker with hard sandbox
# is the only acceptable provider. Host execution would allow arbitrary code
# execution on the host system. If Docker is unavailable, execution must fail.
_INTERACTIVE_PYTHON_REQUIRED_PROVIDER = "docker"
_INTERACTIVE_PYTHON_REQUIRED_SANDBOX_MODE = "hard"


def _enforce_docker_for_interactive_python(
    project_config: dict[str, Any] | None,
    db: Any | None,
) -> dict[str, Any]:
    config = dict(project_config or {})
    config.setdefault("execution_runtime_provider", _INTERACTIVE_PYTHON_REQUIRED_PROVIDER)
    config.setdefault("execution_runtime_sandbox_mode", _INTERACTIVE_PYTHON_REQUIRED_SANDBOX_MODE)
    # Hard sandbox cannot fall back to host
    config["execution_runtime_allow_host_fallback"] = False
    return config


def _docker_available() -> bool:
    return shutil.which("docker") is not None


@dataclass
class InteractivePythonSession:
    id: str
    handle: PersistentProcessHandle
    workspace_root: Path
    execution_runtime: dict[str, Any] = field(default_factory=dict)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


class InteractivePythonManager:
    def __init__(self) -> None:
        self._sessions: dict[str, InteractivePythonSession] = {}

    async def _spawn(
        self,
        *,
        session_id: str | None,
        workspace_root: Path,
        db: Any | None,
        project_config: dict[str, Any] | None,
    ) -> InteractivePythonSession:
        from . import spawn_persistent_stdio_process

        root_module = sys.modules.get("app.services.interactive_python")
        if root_module is None:
            root_module = import_module("app.services.interactive_python")
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

        # Enforce Docker + hard sandbox for user-code execution
        enforced_config = _enforce_docker_for_interactive_python(project_config, db)
        if not _docker_available():
            raise with_error_contract(
                RuntimeError(
                    "Interactive Python requires Docker to execute user code securely. "
                    "Docker is not available on this host."
                ),
                error_code="python_docker_required",
                retryable=False,
            )

        handle = await spawn_process(
            db=db,
            project_config=enforced_config,
            command=[sys.executable, "-m", "app.services.python_runtime_entrypoint"],
            cwd=workspace_root,
            workspace_root=workspace_root,
            stderr_mode="pipe",
        )
        session = InteractivePythonSession(
            id=session_id,
            handle=handle,
            workspace_root=workspace_root,
            execution_runtime=dict(handle.metadata),
        )
        self._sessions[session_id] = session
        return session

    async def _send_command(
        self,
        session: InteractivePythonSession,
        *,
        action: str,
        params: dict[str, Any],
        timeout_sec: int = 45,
    ) -> dict[str, Any]:
        process = session.handle.process
        if process.stdin is None or process.stdout is None:
            raise with_error_contract(
                RuntimeError("Interactive Python worker stdio is not available"),
                error_code="python_transport_unavailable",
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
                RuntimeError("Interactive Python worker exited before sending a response"),
                error_code="python_worker_exited",
                retryable=True,
            )
        response = json.loads(line.decode("utf-8", errors="replace"))
        if str(response.get("id") or "") != request_id:
            raise with_error_contract(
                RuntimeError("Interactive Python worker returned an unexpected response id"),
                error_code="python_protocol_error",
                retryable=False,
            )
        if not response.get("ok"):
            error_payload = response.get("error")
            message = "Interactive Python request failed"
            if isinstance(error_payload, dict):
                message = str(error_payload.get("message") or message)
            elif error_payload:
                message = str(error_payload)
            contract = get_error_contract(error_payload)
            raise with_error_contract(
                RuntimeError(redact_process_output(message)),
                error_code=contract.error_code if error_payload else "python_worker_error",
                retryable=contract.retryable if error_payload else False,
            )
        result = response.get("result")
        if not isinstance(result, dict):
            return {"value": result}
        return {
            key: redact_process_output(value) if key in _CELL_OUTPUT_KEYS and isinstance(value, str) else value
            for key, value in result.items()
        }

    async def execute(
        self,
        *,
        python_session_id: str | None,
        workspace_root: str | None,
        db: Any | None,
        project_config: dict[str, Any] | None,
        action: str,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        session = self._sessions.get(str(python_session_id or "").strip())
        if session is None:
            session = await self._spawn(
                session_id=str(python_session_id or "").strip() or None,
                workspace_root=Path(workspace_root or Path.cwd()).resolve(),
                db=db,
                project_config=project_config,
            )
        result = await self._send_command(session, action=action, params=dict(params or {}))
        payload = {
            "python_session_id": session.id,
            "execution_runtime": dict(session.execution_runtime),
            **result,
        }
        if action == "close":
            await self.close(session.id)
        return payload

    async def close(self, python_session_id: str) -> None:
        session = self._sessions.pop(python_session_id, None)
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


interactive_python_manager = InteractivePythonManager()
