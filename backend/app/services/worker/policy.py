from __future__ import annotations

from datetime import time, timedelta
from decimal import Decimal

from fastapi import HTTPException

from ...models import AgentWorker, WorkerOnboarding
from ...time_utils import ensure_utc, utc_now_aware

DEFAULT_WORKER_KNOWLEDGE_CATEGORIES = [
    "runbooks",
    "service_map",
    "alert_definitions",
    "team_contacts",
]
CRITICAL_CONNECTORS = ("jira", "kubernetes")
AUTONOMY_LEVEL_ORDER = {
    "supervised": 0,
    "semi_auto": 1,
    "autonomous": 2,
    "full_auto": 3,
}
WORKER_ACTION_MIN_LEVEL = {
    "log": "supervised",
    "notify": "supervised",
    "page": "supervised",
    "escalate": "supervised",
    "create_ticket": "semi_auto",
    "diagnose": "semi_auto",
    "auto_fix": "autonomous",
}
DEFAULT_TRUST_DELTAS = {
    "success": 0.05,
    "failure": -0.1,
    "unnecessary_escalation": -0.08,
    "correct_escalation": 0.03,
    "human_overridden": -0.05,
    "human_approved": 0.02,
}


def parse_time(value: str | None) -> time | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        hour, minute = raw.split(":", 1)
        return time(hour=int(hour), minute=int(minute))
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Invalid time value '{raw}'. Use HH:MM.") from exc


def serialize_time(value: time | None) -> str | None:
    return value.strftime("%H:%M") if value else None


def normalize_string_list(value: list[str] | None) -> list[str]:
    return [str(item).strip() for item in value or [] if str(item).strip()]


def normalize_autonomy_level(value: str | None) -> str:
    key = str(value or "supervised").strip().lower()
    if key not in AUTONOMY_LEVEL_ORDER:
        raise HTTPException(status_code=422, detail=f"Invalid autonomy_level '{key}'")
    return key


def clamp_trust_score(value: float | Decimal | int | None) -> float:
    raw = float(value if value is not None else 0.5)
    return max(0.0, min(1.0, round(raw, 4)))


def autonomy_from_trust_score(value: float | Decimal | int | None) -> str:
    score = clamp_trust_score(value)
    if score < 0.3:
        return "supervised"
    if score < 0.6:
        return "semi_auto"
    if score <= 0.85:
        return "autonomous"
    return "full_auto"


def minimum_trust_for_autonomy(level: str) -> float:
    normalized = normalize_autonomy_level(level)
    mapping = {
        "supervised": 0.0,
        "semi_auto": 0.3,
        "autonomous": 0.6,
        "full_auto": 0.86,
    }
    return mapping[normalized]


def sync_worker_autonomy_from_trust(worker: AgentWorker) -> None:
    worker.trust_score = clamp_trust_score(worker.trust_score)
    worker.autonomy_level = autonomy_from_trust_score(worker.trust_score)


def effective_autonomy_level(worker: AgentWorker, onboarding: WorkerOnboarding) -> str:
    ready_at = ensure_utc(onboarding.ready_at)
    if ready_at is None:
        return "supervised"
    warmup_until = ready_at + timedelta(hours=onboarding.warmup_period_hours or 0)
    if utc_now_aware() < warmup_until:
        return "supervised"
    return normalize_autonomy_level(worker.autonomy_level)


def can_worker_execute_action(worker: AgentWorker, onboarding: WorkerOnboarding, action: str | None) -> bool:
    normalized_action = str(action or "log").strip().lower()
    if normalized_action in {item.lower() for item in worker.forbidden_actions or []}:
        return False
    if worker.allowed_actions:
        allowed = {item.lower() for item in worker.allowed_actions or []}
        if normalized_action not in allowed and normalized_action not in {"log", "notify", "page", "escalate"}:
            return False
    required_level = WORKER_ACTION_MIN_LEVEL.get(normalized_action, "supervised")
    current_level = effective_autonomy_level(worker, onboarding)
    return AUTONOMY_LEVEL_ORDER[current_level] >= AUTONOMY_LEVEL_ORDER[required_level]
