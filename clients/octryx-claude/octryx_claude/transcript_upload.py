"""Full session transcripts to the platform, only while the Workspace's switch is on.

Today the platform gets a session's job events, its live progress (no file contents), the redacted digest at
finalize and its usage; the raw Claude Code transcript (``<profile config dir>/projects/<folder>/<session id>.jsonl``)
stays on the Mac. With the Workspace's ``session_transcripts`` switch on (the client policy says so at the start),
a daemon thread next to the launcher's heartbeat reads the new complete lines of the session's transcript and of its
subagents' transcripts (``<folder>/<session id>/subagents/agent-<id>.jsonl``), redacts them (:mod:`transcript_redact`)
and posts them in batches (``POST /sessions/transcript``). It never blocks a tool call or the session: Claude Code
writes the file, this thread only reads it, and every failure is the next round.

Like the device's event outbox (:mod:`device_outbox`) nothing is lost over a sleep or a lost connection: the
transcript itself is the durable buffer and ``transcript-outbox/<session id>.json`` (0600) keeps, per stream, the byte
offset and line the platform acknowledged. A round sends everything after it; a batch the platform already holds is
acknowledged as ``duplicate``. A resumed session continues after what the platform has. A session that ended while
the platform was unreachable is sent by the next session's thread on this Mac (:func:`flush_leftovers`).

When the platform answers ``off`` (an admin switched it off) the thread stops at once and forgets its offsets. Off at
the start: no thread, no file, no call; nothing changes against a launcher without this feature.
"""

from __future__ import annotations

import contextlib
import logging
import os
import re
import threading
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

from .platform import PlatformResult, SessionContext, call_control_plane
from .state import LocalState, read_json, write_private_json
from .transcript_redact import redact_line
from .transcript_streams import (
    _SESSION_ID,
    _entry,
    read_complete_lines,
    stream_files,
)

logger = logging.getLogger(__name__)

OUTBOX_DIR = "transcript-outbox"
INTERVAL_SECONDS = 5.0
TIMEOUT_SECONDS = 30.0
FINAL_FLUSH_SECONDS = 10.0
MAX_BATCH_BYTES = 2 * 1024 * 1024
MAX_BATCH_LINES = 1000
LEFTOVER_DAYS = 7
# ``PreparedSession.extra`` key of a device turn whose Workspace switched transcripts on (``device_session``).
EXTRA_KEY = "session_transcripts"
_JOB_ID = re.compile(r"^[A-Za-z0-9_-]{1,40}$")


def enabled(policy_body: dict[str, Any] | None) -> bool:
    """The client policy's word: on only when the Workspace switched it on."""
    section = (policy_body or {}).get("session_transcripts")
    return isinstance(section, dict) and section.get("enabled") is True


@dataclass
class Shipper:
    """One session's upload: its context, its transcript's id and the acknowledged position per stream."""

    state: LocalState
    context: SessionContext
    config_dir: Path
    claude_session_id: str
    job_id: str = ""
    streams: dict[str, dict[str, int]] = field(default_factory=dict)
    secret_ids: set[str] = field(default_factory=set)
    stopped: bool = False

    @property
    def path(self) -> Path:
        return self.state.root / OUTBOX_DIR / f"{self.claude_session_id}.json"

    def load(self) -> Shipper:
        stored = read_json(self.path) if _SESSION_ID.match(self.claude_session_id) else {}
        streams = stored.get("streams") if isinstance(stored.get("streams"), dict) else {}
        self.streams = {name: {"offset": int(pos.get("offset") or 0), "line": int(pos.get("line") or 0)}
                        for name, pos in streams.items() if isinstance(pos, dict)}
        self.secret_ids = {str(item) for item in stored.get("secret_ids") or []}
        return self

    def save(self, *, done: bool = False) -> None:
        write_private_json(self.path, {
            "streams": self.streams, "secret_ids": sorted(self.secret_ids)[-2000:], "done": done,
            "updated": time.time(), "pid": os.getpid(), "config_dir": str(self.config_dir), "job_id": self.job_id,
            "credential_set": self.state.credential_set,
            "context": {"base_url": self.context.base_url, "session_key": self.context.session_key,
                        "workspace_id": self.context.workspace_id, "work_item": self.context.work_item,
                        "workflow_run": self.context.workflow_run},
        })

    def forget(self) -> None:
        self.path.unlink(missing_ok=True)

    def _post(self, http: httpx.Client, stream: str, first_line: int, lines: list[Any]) -> PlatformResult:
        body: dict[str, Any] = {"claude_session_id": self.claude_session_id, "stream": stream,
                                "first_line": first_line, "lines": lines}
        if self.job_id and _JOB_ID.match(self.job_id):
            body["device_job_id"] = self.job_id
        return call_control_plane(self.state, self.context, "POST", "/sessions/transcript", http=http,
                                  timeout=TIMEOUT_SECONDS, body=body)

    def ship_round(self, http: httpx.Client) -> bool:
        """Send every new complete line once; ``False`` when the round stopped early (unreachable, refused, off)."""
        if self.stopped:
            return False
        for stream, path in sorted(stream_files(self.config_dir, self.claude_session_id).items()):
            if not self._ship_stream(http, stream, path):
                return False
        return True

    def _ship_stream(self, http: httpx.Client, stream: str, path: Path) -> bool:
        position = self.streams.setdefault(stream, {"offset": 0, "line": 0})
        if path.stat().st_size < position["offset"]:  # rewritten under us: go on from its new end
            position["offset"] = path.stat().st_size
        while True:
            raws, _end = read_complete_lines(path, position["offset"])
            if not raws:
                return True
            batch: list[Any] = []
            size = 0
            consumed = position["offset"]
            for raw in raws:
                if batch and (size + len(raw) > MAX_BATCH_BYTES or len(batch) >= MAX_BATCH_LINES):
                    break
                consumed += len(raw) + 1
                if raw.strip():  # an empty line is no transcript line
                    batch.append(redact_line(_entry(raw), self.secret_ids))
                    size += len(raw)
            if not batch:
                position["offset"] = consumed
                continue
            result = self._post(http, stream, position["line"] + 1, batch)
            state = str(result.body.get("state") or "") if result.outcome == "ok" else ""
            if state == "off":
                self.stop_switched_off()
                return False
            if state not in ("stored", "duplicate"):
                return False  # unreachable or refused: the same lines go next round
            position["offset"] = consumed
            position["line"] += len(batch)
            self.save()

    def stop_switched_off(self) -> None:
        self.stopped = True
        self.forget()
        logger.info("transcript upload stopped: the Workspace switched session transcripts off")


def _alive(pid: Any) -> bool:
    if not isinstance(pid, int) or pid <= 0:
        return False
    if pid == os.getpid():
        return True  # the device service runs many turns: another turn of this process owns it
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except OSError:
        return True
    return True


def flush_leftovers(state: LocalState, http: httpx.Client, *, skip: str = "", now: float | None = None) -> None:
    """Send what ended sessions on this Mac still owe (the platform was unreachable at their end)."""
    root = state.root / OUTBOX_DIR
    for path in sorted(root.glob("*.json")) if root.is_dir() else []:
        stored = read_json(path)
        if path.stem == skip or not (stored.get("done") or not _alive(stored.get("pid"))):
            continue  # its own session's thread still sends it
        if (now or time.time()) - float(stored.get("updated") or 0) > LEFTOVER_DAYS * 86400:
            path.unlink(missing_ok=True)  # the platform's retention is shorter than this anyway
            continue
        context = SessionContext.from_env({
            "OCTRYX_BASE_URL": str((stored.get("context") or {}).get("base_url") or ""),
            "OCTRYX_SESSION_KEY": str((stored.get("context") or {}).get("session_key") or ""),
            "OCTRYX_WORKSPACE_ID": str((stored.get("context") or {}).get("workspace_id") or ""),
            "OCTRYX_WORK_ITEM": str((stored.get("context") or {}).get("work_item") or ""),
            "OCTRYX_WORKFLOW_RUN": str((stored.get("context") or {}).get("workflow_run") or ""),
        })
        if context is None:
            path.unlink(missing_ok=True)
            continue
        owner = state.with_credential_set(str(stored.get("credential_set") or ""))
        shipper = Shipper(owner, context, Path(str(stored.get("config_dir") or "")), path.stem,
                          str(stored.get("job_id") or "")).load()
        if shipper.ship_round(http) and not shipper.stopped:
            shipper.forget()  # everything is on the platform


class Running:
    """The upload thread of one session: :meth:`stop` sends what is left once (bounded wait), :meth:`bind` follows
    a transcript id that is known only after the turn (a forked device turn)."""

    def __init__(self, shipper: Shipper, *, interval: float, client_factory: Callable[[], httpx.Client]) -> None:
        self.shipper = shipper
        self._interval = interval
        self._client_factory = client_factory
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._thread = threading.Thread(target=self._loop, name="octryx-transcripts", daemon=True)

    def start(self) -> Running:
        self._thread.start()
        return self

    def bind(self, claude_session_id: str) -> None:
        if not _SESSION_ID.match(claude_session_id or ""):
            return
        with self._lock:
            if claude_session_id != self.shipper.claude_session_id and not self.shipper.stopped:
                shipper = self.shipper
                self.shipper = Shipper(shipper.state, shipper.context, shipper.config_dir, claude_session_id,
                                       shipper.job_id).load()

    def _round(self, http: httpx.Client) -> bool:
        with self._lock:
            return self.shipper.ship_round(http)

    def _loop(self) -> None:
        try:
            with self._client_factory() as http:
                flush_leftovers(self.shipper.state, http, skip=self.shipper.claude_session_id)
                while not self._stop.wait(self._interval) and not self.shipper.stopped:
                    self._round(http)
                if not self.shipper.stopped:  # the session ended: what is left, once
                    if self._round(http):
                        self.shipper.forget()
                    else:
                        self.shipper.save(done=True)
        except Exception:  # noqa: BLE001 - the session never depends on its transcript upload
            logger.warning("transcript upload failed", exc_info=True)
            with contextlib.suppress(Exception):
                self.shipper.save(done=True)

    def stop(self, wait: float = FINAL_FLUSH_SECONDS) -> None:
        self._stop.set()
        self._thread.join(wait)


def start(state: LocalState, context: SessionContext, *, config_dir: Path, claude_session_id: str, job_id: str = "",
          interval: float = INTERVAL_SECONDS,
          client_factory: Callable[[], httpx.Client] = httpx.Client) -> Running | None:
    """The upload thread for a session whose Workspace switched transcripts on; ``None`` without a transcript id."""
    if not _SESSION_ID.match(claude_session_id or ""):
        return None
    shipper = Shipper(state, context, config_dir, claude_session_id, job_id).load()
    return Running(shipper, interval=interval, client_factory=client_factory).start()


@contextlib.contextmanager
def running(state: LocalState, context: SessionContext, *, config_dir: Path, claude_session_id: str, on: bool,
            job_id: str = "", interval: float = INTERVAL_SECONDS,
            client_factory: Callable[[], httpx.Client] = httpx.Client) -> Iterator[Running | None]:
    """Upload while the block runs, when ``on``; off yields ``None`` and does nothing at all."""
    upload = start(state, context, config_dir=config_dir, claude_session_id=claude_session_id, job_id=job_id,
                   interval=interval, client_factory=client_factory) if on else None
    try:
        yield upload
    finally:
        if upload is not None:
            upload.stop()


def start_for_turn(prepared: Any, offer: dict[str, Any]) -> Running | None:
    """A device job's turn (``device_jobs``): on only when ``prepare_session`` found the switch on. A resumed turn
    continues its session's transcript; a fresh or forked one writes under the session key or the id Claude Code
    reports (:meth:`Running.bind` after the turn)."""
    upload = (getattr(prepared, "extra", None) or {}).get(EXTRA_KEY)
    if not isinstance(upload, dict):
        return None
    resume = str(offer.get("resume") or "")
    claude_session_id = resume if resume and not offer.get("fork") else str(prepared.session_key)
    return start(upload["state"], upload["context"], config_dir=Path(upload["config_dir"]),
                 claude_session_id=claude_session_id, job_id=str(offer.get("job_id") or ""))


__all__ = [
    "EXTRA_KEY",
    "Running",
    "Shipper",
    "enabled",
    "flush_leftovers",
    "running",
    "start",
    "start_for_turn",
]
