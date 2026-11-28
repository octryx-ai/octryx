"""The seat allowance windows read from Anthropic's and Codex's rate-limit response headers."""

from __future__ import annotations

import math
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

PREFIX = "anthropic-ratelimit-unified-"
STATUS_REJECTED = "rejected"
LIMIT_PERCENT = 100.0
_MAX_UTILIZATION = 100.0  # a fraction; anything larger is not a utilization
_MIN_EPOCH = 1_600_000_000
_MAX_EPOCH = 4_102_444_800  # 2100-01-01
_STATUS = re.compile(r"^[a-z][a-z_]{0,31}$")


@dataclass(frozen=True, slots=True)
class Allowance:
    five_hour_pct: float | None = None
    five_hour_resets_at: datetime | None = None
    seven_day_pct: float | None = None
    seven_day_resets_at: datetime | None = None
    status: str | None = None

    @property
    def observed(self) -> bool:
        return any(value is not None for value in (
            self.five_hour_pct, self.five_hour_resets_at, self.seven_day_pct, self.seven_day_resets_at, self.status
        ))

    @property
    def limit_reached(self) -> bool:
        if self.status == STATUS_REJECTED:
            return True
        return any(pct is not None and pct >= LIMIT_PERCENT for pct in (self.five_hour_pct, self.seven_day_pct))


def _percent(raw: str | None) -> float | None:
    try:
        value = float(str(raw).strip())
    except (TypeError, ValueError):
        return None
    if not math.isfinite(value) or not 0.0 <= value <= _MAX_UTILIZATION:
        return None
    return round(value * 100.0, 1)


def _reset(raw: str | None) -> datetime | None:
    text = str(raw or "").strip()
    if not text.isdigit():
        return None
    epoch = int(text)
    if not _MIN_EPOCH <= epoch <= _MAX_EPOCH:
        return None
    return datetime.fromtimestamp(epoch, tz=UTC).replace(tzinfo=None)


def _status(raw: str | None) -> str | None:
    text = str(raw or "").strip().lower()
    return text if _STATUS.match(text) else None


_SEVERITY = {STATUS_REJECTED: 3, "allowed_warning": 2, "allowed": 0}


def _worst(*statuses: str | None) -> str | None:
    present = [status for status in statuses if status]
    return max(present, key=lambda status: _SEVERITY.get(status, 1)) if present else None


def parse_allowance(headers: Mapping[str, str]) -> Allowance:
    lowered = {str(name).lower(): str(value) for name, value in headers.items()}

    def get(suffix: str) -> str | None:
        return lowered.get(f"{PREFIX}{suffix}")

    return Allowance(
        five_hour_pct=_percent(get("5h-utilization")),
        five_hour_resets_at=_reset(get("5h-reset")),
        seven_day_pct=_percent(get("7d-utilization")),
        seven_day_resets_at=_reset(get("7d-reset")),
        status=_worst(_status(get("status")), _status(get("5h-status")), _status(get("7d-status"))),
    )


CODEX_PREFIX = "x-codex-"
_MAX_PERCENT = 10_000.0  # the same ceiling as a Claude utilization fraction of 100
_MAX_RESET_AFTER_SECONDS = 400 * 24 * 3600
# codex-rs ``RateLimitReachedType``: the call was refused for one of these limits.
CODEX_LIMIT_REACHED_TYPES = frozenset({
    "rate_limit_reached", "workspace_owner_credits_depleted", "workspace_member_credits_depleted",
    "workspace_owner_usage_limit_reached", "workspace_member_usage_limit_reached",
})


def _codex_percent(raw: str | None) -> float | None:
    try:
        value = float(str(raw).strip())
    except (TypeError, ValueError):
        return None
    if not math.isfinite(value) or not 0.0 <= value <= _MAX_PERCENT:
        return None
    return round(value, 1)


def _reset_after(raw: str | None, now: datetime) -> datetime | None:
    text = str(raw or "").strip()
    if not text.isdigit() or int(text) > _MAX_RESET_AFTER_SECONDS:
        return None
    return now + timedelta(seconds=int(text))


def parse_codex_allowance(headers: Mapping[str, str], *, now: datetime | None = None) -> Allowance:
    lowered = {str(name).lower(): str(value) for name, value in headers.items()}
    moment = now or datetime.now(UTC).replace(tzinfo=None)

    def get(suffix: str) -> str | None:
        return lowered.get(f"{CODEX_PREFIX}{suffix}")

    def resets(window: str) -> datetime | None:
        return _reset(get(f"{window}-reset-at")) or _reset_after(get(f"{window}-reset-after-seconds"), moment)

    reached = str(get("rate-limit-reached-type") or "").strip().lower()
    return Allowance(
        five_hour_pct=_codex_percent(get("primary-used-percent")),
        five_hour_resets_at=resets("primary"),
        seven_day_pct=_codex_percent(get("secondary-used-percent")),
        seven_day_resets_at=resets("secondary"),
        status=STATUS_REJECTED if reached in CODEX_LIMIT_REACHED_TYPES else None,
    )


__all__ = ["CODEX_LIMIT_REACHED_TYPES", "CODEX_PREFIX", "LIMIT_PERCENT", "PREFIX", "STATUS_REJECTED", "Allowance",
           "parse_allowance", "parse_codex_allowance"]
