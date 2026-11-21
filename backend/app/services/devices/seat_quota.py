"""Whether a device's own subscription (the ``seat`` profile) is at its usage limit right now, per engine.

A seat at 100 % of its subscription cannot take more work. A workflow run should not
start a seat turn only to have it fail: the platform remembers the last limit answer of the device's seat and its
reset time, and routes to ``governed`` until then.

No new storage: the answer is in the device's recorded ``turn_finished`` events of failed turns (``result_text`` such
as "You've hit your weekly limit · resets Nov 13 at 11am (Europe/Zurich)"). A later successful seat turn clears it. A
reset time that cannot be read counts for :data:`UNKNOWN_RESET` (the platform tries the seat again after that).

**Structured signals only**: a failed turn counts as the seat's limit when the engine
reported it as such: the launcher's error code (:data:`LIMIT_CODES`: Claude Code's ``rate_limit`` / ``billing_error``,
Codex's usage limit, an HTTP 429), or the account's own limit message, which is matched as an exact known opening
(:data:`ACCOUNT_LIMIT_MESSAGES`), never as words anywhere in the text: free text that
an agent wrote ("recipe limit reached: 1000") must not move a run off its seat; a sentence that mentions "rate limit" or
"usage limit" is the agent's, not the account's.

**Per device and engine**: a Claude seat at its limit does not hold back the device's Codex seat (the person's
ChatGPT login) and the other way round; the limit is read from the device's jobs of that engine only.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import DeviceJob
from ...models.agent.device_job import DeviceJobEvent
from ...time_utils import utc_now
from ..agent_gateway.engine_keys import ENGINE_CLAUDE_CODE, ENGINE_CODEX

#: The launcher's fixed codes of a turn that ended on the account's limit (``turn_finished.error``): Claude Code's
#: ``rate_limit`` / ``billing_error`` (its result ``error``), Codex's ``usage_limit`` / ``rate_limit``, an HTTP 429.
LIMIT_CODES = frozenset({"rate_limit", "usage_limit", "billing_error", "http_429"})
#: The accounts' own limit answers, as they open (Claude Code's "You've hit your weekly limit · resets …", its
#: "Claude AI usage limit reached|<epoch>", the API's 429, Codex's "You've hit your usage limit. … try again in …").
ACCOUNT_LIMIT_MESSAGES = ("you've hit your weekly limit", "you've hit your session limit",
                          "you've hit your usage limit", "you've hit your limit", "claude ai usage limit reached",
                          "api error: 429")
UNKNOWN_RESET = timedelta(hours=1)
LOOKBACK = timedelta(days=8)
_RESET = re.compile(
    r"resets\s+(?:(?P<month>[A-Z][a-z]{2,8})\s+(?P<day>\d{1,2})\s+at\s+)?(?P<hour>\d{1,2})(?::(?P<minute>\d{2}))?"
    r"\s*(?P<ampm>am|pm)(?:\s*\((?P<zone>[A-Za-z_]+/[A-Za-z_]+)\))?", re.IGNORECASE)
_MONTHS = {name: number for number, name in enumerate(
    ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"), start=1)}


_EPOCH = re.compile(r"usage limit reached\|(?P<epoch>\d{10})\b", re.IGNORECASE)
_TRY_AGAIN = re.compile(r"try again in\s+(?:(?P<days>\d+)\s*days?)?[\s,]*(?:(?P<hours>\d+)\s*hours?)?[\s,]*"
                        r"(?:(?P<minutes>\d+)\s*minutes?)?", re.IGNORECASE)


def is_limit_answer(text: str) -> bool:
    """The text is one of the accounts' own limit answers (an exact known opening, see the module)."""
    lowered = " ".join(str(text or "").replace("\u2019", "'").split()).lower()
    return bool(lowered) and lowered.startswith(ACCOUNT_LIMIT_MESSAGES)


def is_limit_failure(code: str, text: str = "", *, http_status: Any = None) -> bool:
    """A failed turn ended on the account's limit: the launcher's code, an HTTP 429, or the account's own answer."""
    return str(code or "") in LIMIT_CODES or http_status == 429 or is_limit_answer(text)


def known_reset(text: str, *, said_at: datetime) -> datetime | None:
    """The reset as naive UTC when the answer names it, ``None`` when it does not (see :func:`reset_time`)."""
    text = str(text or "")
    epoch = _EPOCH.search(text)
    if epoch is not None:
        return datetime.fromtimestamp(int(epoch["epoch"]), tz=UTC).replace(tzinfo=None)
    again = _TRY_AGAIN.search(text)
    if again is not None and any(again.group(key) for key in ("days", "hours", "minutes")):
        return said_at + timedelta(days=int(again["days"] or 0), hours=int(again["hours"] or 0),
                                   minutes=int(again["minutes"] or 0))
    match = _RESET.search(text)
    if match is None:
        return None
    try:
        zone = ZoneInfo(match["zone"]) if match["zone"] else ZoneInfo("UTC")
        local_said = said_at.replace(tzinfo=ZoneInfo("UTC")).astimezone(zone)
        hour = int(match["hour"]) % 12 + (12 if match["ampm"].lower() == "pm" else 0)
        minute = int(match["minute"] or 0)
        if match["month"]:
            month = _MONTHS[match["month"][:3].lower()]
            local = local_said.replace(month=month, day=int(match["day"]), hour=hour, minute=minute, second=0,
                                       microsecond=0)
            if local < local_said - timedelta(days=1):
                local = local.replace(year=local.year + 1)
        else:
            local = local_said.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if local <= local_said:
                local += timedelta(days=1)
        return local.astimezone(ZoneInfo("UTC")).replace(tzinfo=None)
    except (KeyError, ValueError):
        return None


def reset_time(text: str, *, said_at: datetime) -> datetime:
    """The reset as naive UTC, from the answer's "resets <Mon> <d> at <h>[:mm]am|pm (<Zone>)" (or Claude Code's
    "|<epoch>", Codex's "try again in <d> days <h> hours"); else said_at + :data:`UNKNOWN_RESET`."""
    return known_reset(text, said_at=said_at) or said_at + UNKNOWN_RESET


@dataclass(frozen=True)
class SeatLimit:
    until: datetime        # naive UTC
    reset_known: bool      # the account named its reset (else ``until`` is the report + UNKNOWN_RESET)
    said: str              # the account's answer or the launcher's code


def turn_limit(body: dict[str, Any], *, said_at: datetime) -> SeatLimit | None:
    """The limit a failed seat turn's ``turn_finished`` body reports, ``None`` when it reports none."""
    if str(body.get("status") or "") in ("", "success"):
        return None
    text = str(body.get("result_text") or "")
    code = str(body.get("error") or body.get("reason") or "")
    if not is_limit_failure(code, text, http_status=body.get("http_status")):
        return None
    reset = rate_limit_reset(body.get("seat_rate_limits")) or known_reset(text, said_at=said_at)
    words = " ".join(text.split())[:200] if is_limit_answer(text) else code
    return SeatLimit(reset or said_at + UNKNOWN_RESET, reset is not None, words)


def rate_limit_reset(limits: Any) -> datetime | None:
    """The reset (naive UTC) of the seat's exhausted window as Codex recorded it (``seat_rate_limits``: the launcher
    reads the thread's rollout, ``{primary|secondary: {used_percent, window_minutes, resets_at}}``); the latest one
    when both are used up, so a run does not pause with an unknown reset while the rollout
    names one."""
    if not isinstance(limits, dict):
        return None
    resets = []
    for window in limits.values():
        if not isinstance(window, dict):
            continue
        used, at = window.get("used_percent"), window.get("resets_at")
        if isinstance(used, (int, float)) and used >= 100 and isinstance(at, (int, float)) and at > 0:
            resets.append(datetime.fromtimestamp(float(at), tz=UTC).replace(tzinfo=None))
    return max(resets) if resets else None


def _engine_filter(engine: str):
    if engine == ENGINE_CODEX:
        return DeviceJob.engine == ENGINE_CODEX
    # An empty engine is Claude Code (``DeviceJob.engine`` before the job's first offer).
    return or_(DeviceJob.engine.is_(None), DeviceJob.engine == "", DeviceJob.engine == ENGINE_CLAUDE_CODE)


async def seat_limit(db: AsyncSession, device_id: str, *, engine: str = ENGINE_CLAUDE_CODE,
                     now: datetime | None = None, chosen_at: datetime | None = None) -> SeatLimit | None:
    """The device's seat limit for ``engine`` that still holds, ``None`` when it is not known to be at its limit.

    ``chosen_at``: when a person chose the seat for this work. A limit the seat reported before that choice does not
    hold it back (an old "resets Nov 13" answer must not keep every run off a seat that works again; a seat turn that
    does hit the limit still switches to governed at once)."""
    now = now or utc_now()
    rows = (await db.execute(
        select(DeviceJobEvent.body, DeviceJobEvent.created_at)
        .join(DeviceJob, DeviceJob.id == DeviceJobEvent.job_id)
        .where(DeviceJob.device_id == device_id, DeviceJob.profile == "seat", _engine_filter(engine),
               DeviceJobEvent.type == "turn_finished", DeviceJobEvent.created_at >= now - LOOKBACK)
        .order_by(DeviceJobEvent.created_at.desc()).limit(20)
    )).all()
    for body, created_at in rows:
        body = body if isinstance(body, dict) else {}
        if str(body.get("status") or "") == "success":
            # The seat worked after its last limit. A successful turn's text is the agent's own summary, never the
            # account's limit answer (the launcher reports that turn as ``error``: Claude Code's ``is_error``). An
            # implement summary listing the CLI message "recipe limit reached: 1000" would otherwise
            # move the run off its seat onto governed, where the rework turn can fail.
            return None
        limit = turn_limit(body, said_at=created_at)
        if limit is not None:
            if chosen_at is not None and _aware(created_at) < _aware(chosen_at):
                return None  # chosen after the limit was reported: the seat is tried; a limit answer falls back
            return limit if limit.until > now else None
    return None


async def seat_limited_until(db: AsyncSession, device_id: str, *, engine: str = ENGINE_CLAUDE_CODE,
                             now: datetime | None = None, chosen_at: datetime | None = None) -> datetime | None:
    """The time the device's ``engine`` seat is usable again, or ``None`` (see :func:`seat_limit`)."""
    limit = await seat_limit(db, device_id, engine=engine, now=now, chosen_at=chosen_at)
    return limit.until if limit is not None else None


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


__all__ = ["ACCOUNT_LIMIT_MESSAGES", "LIMIT_CODES", "SeatLimit", "is_limit_answer", "is_limit_failure", "known_reset",
           "rate_limit_reset", "reset_time", "seat_limit", "seat_limited_until", "turn_limit"]
