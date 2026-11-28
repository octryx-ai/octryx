"""PTY (pseudo-terminal) session manager."""

from __future__ import annotations

import asyncio
import os
import sys
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..persistent_process_runtime import spawn_persistent_pty_process

_IS_UNIX = sys.platform != "win32"

if _IS_UNIX:
    import fcntl
    import pty
    import struct
    import termios


@dataclass
class PTYSession:
    id: str
    pid: int
    master_fd: int
    status: str = "running"  # running | closed
    execution_runtime: dict[str, Any] = field(default_factory=dict)
    # Rolling output buffer (max 512 KB)
    buffer: bytearray = field(default_factory=bytearray)
    # Set of async queues - one per WebSocket subscriber
    subscribers: set[asyncio.Queue] = field(default_factory=set)

    MAX_BUFFER = 512 * 1024

    def push_output(self, data: bytes) -> None:
        self.buffer.extend(data)
        if len(self.buffer) > self.MAX_BUFFER:
            del self.buffer[: len(self.buffer) - self.MAX_BUFFER]
        for queue in list(self.subscribers):
            try:
                queue.put_nowait(data)
            except asyncio.QueueFull:
                pass

    def subscribe(self) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue(maxsize=256)
        self.subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue) -> None:
        self.subscribers.discard(queue)


class PTYManager:
    """Singleton that manages all active PTY sessions."""

    def __init__(self) -> None:
        self._sessions: dict[str, PTYSession] = {}

    async def create(
        self,
        cwd: str | None = None,
        command: str | None = None,
        env: dict[str, str] | None = None,
        *,
        db: Any | None = None,
        project_config: dict[str, Any] | None = None,
    ) -> PTYSession:
        if not _IS_UNIX:
            raise RuntimeError("PTY sessions are not supported on Windows.")

        session_id = str(uuid.uuid4())
        shell = command or os.environ.get("SHELL", "/bin/bash")
        work_dir = cwd or os.path.expanduser("~")
        resolved_dir = Path(work_dir).resolve() if os.path.isdir(work_dir) else Path.home()
        merged_env = {**os.environ, **(env or {})}
        merged_env["TERM"] = "xterm-256color"

        # Open a PTY pair. The slave end becomes stdin/stdout/stderr of the
        # child process; the master end is kept by the parent for I/O.
        master_fd, slave_fd = pty.openpty()

        # Set initial window size (80x24)
        try:
            winsize = struct.pack("HHHH", 24, 80, 0, 0)
            fcntl.ioctl(slave_fd, termios.TIOCSWINSZ, winsize)
        except OSError:
            pass

        handle = await spawn_persistent_pty_process(
            db=db,
            project_config=project_config,
            shell_command=shell,
            cwd=resolved_dir,
            workspace_root=resolved_dir,
            master_fd=master_fd,
            slave_fd=slave_fd,
            env=merged_env,
        )
        proc = handle.process
        os.close(slave_fd)

        session = PTYSession(
            id=session_id,
            pid=proc.pid,
            master_fd=master_fd,
            execution_runtime=dict(handle.metadata),
        )
        self._sessions[session_id] = session

        try:
            loop = asyncio.get_event_loop()
            loop.add_reader(master_fd, self._on_master_readable, session_id)
        except RuntimeError:
            # No running event loop yet (for example during tests). Readers are
            # added lazily when the WebSocket connects.
            pass

        return session

    def close(self, session_id: str) -> None:
        session = self._sessions.get(session_id)
        if not session:
            return
        session.status = "closed"
        try:
            loop = asyncio.get_event_loop()
            loop.remove_reader(session.master_fd)
        except Exception:
            pass
        try:
            os.kill(session.pid, 9)
        except (ProcessLookupError, OSError):
            pass
        try:
            os.waitpid(session.pid, os.WNOHANG)
        except ChildProcessError:
            pass
        try:
            os.close(session.master_fd)
        except OSError:
            pass
        session.push_output(b"\x00__EXIT__\x00")
        del self._sessions[session_id]

    def stop_all(self) -> None:
        for session_id in list(self._sessions):
            self.close(session_id)

    def write(self, session_id: str, data: str | bytes) -> None:
        session = self._sessions.get(session_id)
        if not session or session.status != "running":
            return
        if isinstance(data, str):
            data = data.encode("utf-8")
        try:
            os.write(session.master_fd, data)
        except OSError:
            self.close(session_id)

    def resize(self, session_id: str, cols: int, rows: int) -> None:
        if not _IS_UNIX:
            return
        session = self._sessions.get(session_id)
        if not session or session.status != "running":
            return
        try:
            winsize = struct.pack("HHHH", rows, cols, 0, 0)
            fcntl.ioctl(session.master_fd, termios.TIOCSWINSZ, winsize)
        except OSError:
            pass

    def _on_master_readable(self, session_id: str) -> None:
        session = self._sessions.get(session_id)
        if not session:
            return
        try:
            data = os.read(session.master_fd, 4096)
            if data:
                session.push_output(data)
        except OSError:
            self.close(session_id)

    def list(self) -> list[dict[str, Any]]:
        return [
            {
                "id": session.id,
                "pid": session.pid,
                "status": session.status,
                "buffer_size": len(session.buffer),
                "execution_runtime": session.execution_runtime,
            }
            for session in self._sessions.values()
        ]

    def get(self, session_id: str) -> PTYSession | None:
        return self._sessions.get(session_id)


pty_manager = PTYManager()
