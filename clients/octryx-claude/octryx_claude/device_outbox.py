"""The device's on-disk replay buffer of sequenced job messages.

Every message a job sends to the platform (``job_accepted``, ``job_event``, ``approval_request``,
``job_finished``, …) gets the next ``seq`` of its job's stream and is appended to
``device-outbox/<job_id>.jsonl`` (0600) before it is sent. The platform acknowledges what it stored; acknowledged
entries are dropped. After a reconnect the device replays everything after the platform's last stored ``seq``,
so a laptop that sleeps loses nothing and nothing is stored twice.

The buffer is bounded per job (:data:`MAX_PENDING`); a full buffer refuses the append (``OutboxFullError``) and
the job runner stops that job instead of dropping events silently.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

from .state import LocalState

OUTBOX_DIR = "device-outbox"
MAX_PENDING = 5000
_STREAM = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


class OutboxFullError(Exception):
    pass


class Outbox:
    def __init__(self, state: LocalState) -> None:
        self.root = state.ensure().root / OUTBOX_DIR
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self._pending: dict[str, list[dict[str, Any]]] = {}
        self._next: dict[str, int] = {}
        for path in sorted(self.root.glob("*.jsonl")):
            self._load(path.stem)

    def _path(self, stream: str) -> Path:
        if not _STREAM.match(stream):
            raise ValueError("stream_invalid")
        return self.root / f"{stream}.jsonl"

    def _load(self, stream: str) -> None:
        entries: list[dict[str, Any]] = []
        acked = 0
        try:
            for line in self._path(stream).read_text(encoding="utf-8").splitlines():
                try:
                    entry = json.loads(line)
                except ValueError:
                    continue
                if entry.get("acked") is not None:
                    acked = max(acked, int(entry["acked"]))
                elif isinstance(entry.get("seq"), int):
                    entries.append(entry)
        except (OSError, ValueError):
            return
        self._pending[stream] = [entry for entry in entries if entry["seq"] > acked]
        self._next[stream] = max([acked, *(entry["seq"] for entry in entries)]) + 1

    def _write(self, stream: str, acked: int) -> None:
        path = self._path(stream)
        pending = self._pending.get(stream, [])
        if not pending and acked >= self._next.get(stream, 1) - 1:
            # Everything stored: keep only the high-water mark so the next seq never repeats.
            lines = [json.dumps({"acked": acked})]
        else:
            lines = [json.dumps({"acked": acked}), *(json.dumps(entry) for entry in pending)]
        tmp = path.with_suffix(".tmp")
        fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write("\n".join(lines) + "\n")
        os.replace(tmp, path)

    def append(self, stream: str, message_type: str, body: dict[str, Any]) -> dict[str, Any]:
        pending = self._pending.setdefault(stream, [])
        if len(pending) >= MAX_PENDING:
            raise OutboxFullError(stream)
        seq = self._next.get(stream, 1)
        self._next[stream] = seq + 1
        entry = {"seq": seq, "type": message_type, "body": body}
        pending.append(entry)
        fd = os.open(str(self._path(stream)), os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        with os.fdopen(fd, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry) + "\n")
        return entry

    def ack(self, stream: str, seq: int) -> None:
        pending = self._pending.get(stream)
        if pending is None:
            return
        self._pending[stream] = [entry for entry in pending if entry["seq"] > seq]
        self._write(stream, seq)

    def pending(self, stream: str, after: int = 0) -> list[dict[str, Any]]:
        return [entry for entry in self._pending.get(stream, []) if entry["seq"] > after]

    def streams(self) -> list[str]:
        return [stream for stream, entries in self._pending.items() if entries]

    def forget(self, stream: str) -> None:
        """A finished, fully acknowledged job: its file goes."""
        if self._pending.get(stream):
            return
        self._pending.pop(stream, None)
        self._next.pop(stream, None)
        self._path(stream).unlink(missing_ok=True)


__all__ = ["MAX_PENDING", "Outbox", "OutboxFullError"]
