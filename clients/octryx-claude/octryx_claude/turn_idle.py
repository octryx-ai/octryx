"""A ``claude -p`` run turn that only waits for a wakeup has ended: the launcher ends its process.

``claude -p`` keeps its process alive while a wakeup is pending (ScheduleWakeup as a "fallback check" while an agent
runs, or to "retry once the sandbox lets Chromium launch"), although the turn's work is done at its Stop.

A run turn's background work wakes the session by itself (each task's completion notice), so a wakeup never has to:
once the session's Stop is the latest thing in its transcript, no background task this process started is still
running, and the process has not exited on its own for :data:`GRACE_SECONDS`, the only thing left is the wakeup, and
the job manager ends the process (``plain_driver``). Its deferred Stop is then judged as always.

``claude -p`` stops a background agent 600 s after the main session's Stop and sends no completion notice for it, so
the session would sleep on its wakeup until the job's limit. Such an agent, whose own transcript ends with Claude
Code's interrupt
marker, is over (:func:`stopped_agents`), and the turn reports it plainly. An agent the session resumed with
SendMessage (``resumedAgentId``) runs again until its notice and counts as running.
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any

GRACE_SECONDS = 20.0  # a ``claude -p`` with nothing pending exits about a second after its Stop
POLL_SECONDS = 5.0
# A task-notification's ``<status>`` once the task is over; anything else (a Monitor's event) keeps it running.
_ENDED = frozenset({"completed", "failed", "killed", "stopped", "cancelled", "canceled", "error", "timed_out"})
_INTERRUPTED = "[Request interrupted by user"
STOPPED_AGENT_NOTE = ("A background agent was stopped by Claude Code 10 min after the main session ended; its work is "
                      "incomplete: {agents}.")
_NOTICE = re.compile(r"<task-id>([^<]+)</task-id>.*?<status>([^<]+)</status>", re.DOTALL)


def _when(entry: dict[str, Any]) -> float | None:
    raw = entry.get("timestamp")
    if not isinstance(raw, str) or not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def _entries(transcript: Path, since: float) -> list[tuple[float, dict[str, Any]]]:
    found: list[tuple[float, dict[str, Any]]] = []
    try:
        with transcript.open(encoding="utf-8", errors="replace") as handle:
            for line in handle:
                try:
                    entry = json.loads(line)
                except ValueError:
                    continue
                when = _when(entry) if isinstance(entry, dict) else None
                if when is not None and when >= since:
                    found.append((when, entry))
    except OSError:
        return []
    return found


def _launched(entry: dict[str, Any]) -> str:
    """The id of a background task a tool result started: an async Agent, a background Bash, a Monitor."""
    result = entry.get("toolUseResult")
    if not isinstance(result, dict):
        return ""
    if result.get("isAsync") and result.get("agentId"):
        return str(result["agentId"])
    if result.get("resumedAgentId"):  # SendMessage resumed a stopped agent: it runs again until its notice
        return str(result["resumedAgentId"])
    return str(result.get("backgroundTaskId") or result.get("taskId") or "")


def _notice_text(entry: dict[str, Any]) -> str:
    if entry.get("type") == "queue-operation":
        return str(entry.get("content") or "")
    return ""


def _agent_transcript(transcript: Path, agent_id: str) -> Path:
    return transcript.parent / transcript.stem / "subagents" / f"agent-{agent_id}.jsonl"


def _stopped(agent: Path) -> bool:
    """The agent's own transcript ends with Claude Code's interrupt marker: nothing of it runs any more."""
    last = None
    try:
        with agent.open(encoding="utf-8", errors="replace") as handle:
            for line in handle:
                try:
                    entry = json.loads(line)
                except ValueError:
                    continue
                if isinstance(entry, dict) and entry.get("type") in ("user", "assistant"):
                    last = entry
    except OSError:
        return False
    content = ((last or {}).get("message") or {}).get("content") if isinstance(last, dict) else None
    blocks = content if isinstance(content, list) else [{"type": "text", "text": content}] if content else []
    return (last or {}).get("type") == "user" and any(
        isinstance(block, dict) and str(block.get("text") or "").startswith(_INTERRUPTED) for block in blocks)


def _unfinished(transcript: Path, since: float) -> set[str]:
    """Tasks whose latest event since ``since`` is their start or resume, not an end notice (in transcript order: a
    stopped agent's notice, then SendMessage resuming it, leaves it running)."""
    running: dict[str, bool] = {}
    for _when_at, entry in _entries(transcript, since):
        if task := _launched(entry):
            running[task] = True
        for task_id, status in _NOTICE.findall(_notice_text(entry)):
            if status.strip().lower() in _ENDED:
                running[task_id.strip()] = False
    return {task for task, active in running.items() if active}


def stopped_agents(transcript: Path, since: float) -> set[str]:
    """Agents started (or resumed) at or after ``since``, without a completion notice, that Claude Code stopped."""
    return {task for task in _unfinished(transcript, since) if _stopped(_agent_transcript(transcript, task))}


def open_tasks(transcript: Path, since: float) -> set[str]:
    """Background tasks started at or after ``since`` whose completion notice has not arrived and that still run."""
    return {task for task in _unfinished(transcript, since) if not _stopped(_agent_transcript(transcript, task))}


def resumed_after(transcript: Path, moment: float) -> bool:
    """Whether the session did anything after ``moment``: a message, or a queued prompt or notice that wakes it."""
    return any(entry.get("type") in ("user", "assistant", "queue-operation")
               for _when_at, entry in _entries(transcript, moment + 0.001))


def last_text(transcript: Path, since: float) -> str:
    """The session's last answer text (the result ``claude -p`` would have printed)."""
    text = ""
    for _when_at, entry in _entries(transcript, since):
        if entry.get("type") != "assistant" or entry.get("isSidechain"):
            continue
        for block in (entry.get("message") or {}).get("content") or []:
            if isinstance(block, dict) and block.get("type") == "text" and block.get("text"):
                text = str(block["text"])
    return text


def only_waiting(stop_file: Path, since: float, now: float) -> Path | None:
    """The transcript when the process started at ``since`` has nothing left but a wakeup, else ``None``."""
    try:
        stopped = os.stat(stop_file).st_mtime
        stop = json.loads(stop_file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if stopped < since or now - stopped < GRACE_SECONDS or not isinstance(stop, dict):
        return None
    transcript = Path(str(stop.get("transcript_path") or ""))
    if not transcript.is_file() or resumed_after(transcript, stopped) or open_tasks(transcript, since):
        return None
    return transcript


__all__ = ["GRACE_SECONDS", "POLL_SECONDS", "STOPPED_AGENT_NOTE", "last_text", "only_waiting", "open_tasks",
           "resumed_after", "stopped_agents"]
