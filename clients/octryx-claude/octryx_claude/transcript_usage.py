"""A turn's token usage from its session transcript: what the platform prices every Claude Code turn at.

A turn may end without a result JSON: the launcher ends a run turn 20 s after the session's Stop when only a wakeup
is pending (``turn_idle``), and a process may crash or be killed. Its work still counts in the run's cost.

Every assistant message in the transcript carries the API's ``usage``; Claude Code writes one line per content block
with the same message id and the same usage, so each message counts once. The subagents' transcripts
(``<session id>/subagents/agent-<id>.jsonl``) count too, as their cost is part of the turn's ``total_cost_usd``.
No price is applied here: the launcher reports the tokens per model (``usage.by_model``) and the platform prices them
from its model catalog (``services/devices/turn_cost``), the price table it keeps for every model.

Claude Code's ``total_cost_usd`` is the running total of the whole session, restored on every
``--resume``, so it is no turn's cost. Every turn therefore reports its transcript usage, also when Claude Code printed
a result (its ``cost_usd`` stays as information); the result's own ``usage`` is the fallback when the transcript has
none. The 1-hour prompt-cache writes are counted on their own (``cache_creation_1h_input_tokens``): they cost 2x the
input price, the 5-minute ones 1.25x.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from .transcript_streams import stream_files
from .turn_idle import _entries

SOURCE = "transcript"
TOKEN_FIELDS = ("input_tokens", "output_tokens", "cache_read_input_tokens", "cache_creation_input_tokens")
ONE_HOUR_WRITES = "cache_creation_1h_input_tokens"


def _count(value: Any) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else 0


def transcripts(config_dir: Path, claude_session_id: str) -> list[Path]:
    """The session's transcript and its subagents', found under the profile's ``projects`` folder."""
    return list(stream_files(config_dir, claude_session_id).values())


def turn_usage(paths: list[Path], since: float) -> dict[str, Any] | None:
    """Usage of the messages written at or after ``since``, Claude-shaped totals plus ``by_model``; ``None`` if none."""
    seen: set[str] = set()
    by_model: dict[str, dict[str, int]] = {}
    for path in paths:
        for _when, entry in _entries(path, since):
            message = entry.get("message") if entry.get("type") == "assistant" else None
            usage = message.get("usage") if isinstance(message, dict) else None
            if not isinstance(usage, dict):
                continue
            key = str(message.get("id") or entry.get("requestId") or entry.get("uuid") or "")
            if key and key in seen:
                continue
            seen.add(key)
            model = str(message.get("model") or "")
            if not model or model.startswith("<"):  # ``<synthetic>`` messages cost nothing
                continue
            row = by_model.setdefault(model, dict.fromkeys((*TOKEN_FIELDS, ONE_HOUR_WRITES), 0))
            for name in TOKEN_FIELDS:
                row[name] += _count(usage.get(name))
            detail = usage.get("cache_creation")
            row[ONE_HOUR_WRITES] += _count(detail.get("ephemeral_1h_input_tokens")) if isinstance(detail, dict) else 0
    if not by_model:
        return None
    totals = {name: sum(row[name] for row in by_model.values()) for name in (*TOKEN_FIELDS, ONE_HOUR_WRITES)}
    return {**totals, "by_model": by_model, "source": SOURCE}


def turn_streams(prepared: Any, offer: dict[str, Any], result: dict[str, Any]) -> dict[str, Path]:
    """The transcripts of the session a turn ran in, by stream: the id the driver reported, else the resumed session
    (not forked), else the session key (``--session-id``)."""
    env = getattr(prepared, "env", None) or {}
    home = env.get("CLAUDE_CONFIG_DIR") or os.environ.get("CLAUDE_CONFIG_DIR") or ""
    config_dir = Path(home) if home else Path.home() / ".claude"
    resume = str(offer.get("resume") or "") if not offer.get("fork") else ""
    session = str(result.get("claude_session_id") or resume or getattr(prepared, "session_key", "") or "")
    return stream_files(config_dir, session) if session else {}


def for_turn(prepared: Any, offer: dict[str, Any], result: dict[str, Any], started: float) -> dict[str, Any] | None:
    """The usage of a turn that started at ``started``, read from the transcripts of the session it ran in."""
    streams = turn_streams(prepared, offer, result)
    return turn_usage(list(streams.values()), started) if streams else None


__all__ = ["ONE_HOUR_WRITES", "SOURCE", "TOKEN_FIELDS", "for_turn", "transcripts", "turn_streams", "turn_usage"]
