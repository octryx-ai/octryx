"""A review attempt's bookkeeping: claiming a waiting run, retryable outcomes, usage, shallow reviews, findings."""

from __future__ import annotations

import uuid
from datetime import timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ....models import WorkflowRun
from ....time_utils import ensure_utc, utc_now
from ..records import WorkflowRunError, lock_run
from ..states import STATUS_WAITING, WAITING_REVIEW
from .model import DISPATCH_OWNER

# A review takes well under a minute; an attempt older than this died with its process.
STALE_ATTEMPT_MINUTES = 6


def _waiting(run: WorkflowRun) -> dict[str, Any]:
    return dict(dict(run.node_state or {}).get("waiting") or {})


RETRYABLE_NO_DECISION = ("model_unavailable", "invalid_verdict")


def _retryable(reason: str) -> bool:
    return any(reason == code or reason.startswith(f"{code}:") for code in RETRYABLE_NO_DECISION)


def _due(run: WorkflowRun, now: Any) -> bool:
    if run.status != STATUS_WAITING or run.waiting_kind != WAITING_REVIEW:
        return False
    retry_at = _waiting(run).get("retry_at")
    if retry_at and ensure_utc(now) < ensure_utc(_parse(retry_at)):
        return False
    started = _waiting(run).get("started_at")
    return not started or ensure_utc(now) - ensure_utc(_parse(started)) >= timedelta(minutes=STALE_ATTEMPT_MINUTES)


def _parse(value: Any):
    from datetime import datetime

    return datetime.fromisoformat(str(value))


async def _claim_attempt(db: AsyncSession, run: WorkflowRun) -> str | None:
    try:
        run = await lock_run(db, run)
    except WorkflowRunError:
        return None
    if not _due(run, utc_now()):
        return None
    attempt = uuid.uuid4().hex
    run.node_state = {**dict(run.node_state or {}), "waiting": {
        **_waiting(run), "attempt": attempt, "started_at": utc_now().isoformat()}}
    await db.commit()
    return attempt


def _attributed(run: WorkflowRun, row: Any) -> Any:
    from ...observability import attribution, live_state

    def field(name: str) -> Any:
        return getattr(run, name, None)

    return attribution.attach(row, run=field("id"), ticket=field("ticket_key"), workflow=field("workflow_key"),
                              workspace=field("project_id"), role="review", phase=field("current_node_id"),
                              epic=live_state.EPIC_OF_ITEM.get(str(field("work_item_id") or "")))


async def _record_usage(db: AsyncSession, run: WorkflowRun, usage: Any, attempt: str) -> None:
    from ....models import UsageEvent
    from ...budget import compute_usage_event_cost_attribution
    from ..records import main_session_id

    session_id = await main_session_id(db, run)
    if usage is None or not session_id or not (usage.tokens_in or usage.tokens_out):
        return
    provider, model = (usage.provider or DISPATCH_OWNER)[:100], (usage.model or "unknown")[:100]
    if getattr(usage, "route", "") == "seat":
        # The person's own subscription (``review.seat``): no platform cost; the run's budget still counts it at list
        # price (``octryx.model_guard.run_spend`` reads the model and tokens of this event).
        from ...budget.api_equivalent import api_equivalent_usd, stored
        from ...model_gateway.inbound.seat_transcript import SEAT_COST_SOURCE, SEAT_COST_STATUS

        equivalent = api_equivalent_usd(model, {"input_tokens": usage.tokens_in, "output_tokens": usage.tokens_out})
        db.add(_attributed(run, UsageEvent(
            id=str(uuid.uuid4()), session_id=session_id, user_id=run.requested_by, provider=provider, model=model,
            tokens_in=usage.tokens_in, tokens_out=usage.tokens_out, cost=0, list_cost=stored(equivalent),
            cost_source=SEAT_COST_SOURCE,
            cost_status=SEAT_COST_STATUS, request_id=f"{DISPATCH_OWNER}:{attempt}", dispatch_owner=DISPATCH_OWNER)))
        return
    attribution = await compute_usage_event_cost_attribution(
        db, provider=provider, model=model, tokens_in=usage.tokens_in, tokens_out=usage.tokens_out,
        driver=usage.driver or None)
    cost = attribution.cost
    if getattr(usage, "over_tier_in", 0) and getattr(usage, "tier_factor", 1) > 1:
        # Calls above the model's price tier cost the step's factor on all their tokens (``model.PRICE_TIERS``);
        # the catalog price is the one below the tier.
        over = await compute_usage_event_cost_attribution(
            db, provider=provider, model=model, tokens_in=usage.over_tier_in, tokens_out=usage.over_tier_out,
            driver=usage.driver or None)
        cost = cost + over.cost * (usage.tier_factor - 1)
    db.add(_attributed(run, UsageEvent(
        id=str(uuid.uuid4()), session_id=session_id, user_id=run.requested_by, provider=provider, model=model,
        tokens_in=usage.tokens_in, tokens_out=usage.tokens_out, cost=cost,
        cost_source=attribution.cost_source or None, cost_status=attribution.status,
        request_id=f"{DISPATCH_OWNER}:{attempt}", dispatch_owner=DISPATCH_OWNER)))


# Every verdict's findings stay with its event, bounded, so earlier rounds can still be judged.
MAX_KEPT_FINDINGS = 80
MAX_KEPT_TEXT = 600


async def shallow_review(db: AsyncSession, verdict: Any, usage: Any, diff_lines: int) -> dict[str, Any] | None:
    from ...agent_gateway.review_keys import SHALLOW_DEFAULTS, ReviewPolicyError
    from .choice import installation_defaults

    try:
        limits = {**SHALLOW_DEFAULTS, **dict((await installation_defaults(db)).get("shallow") or {})}
    except ReviewPolicyError:
        limits = dict(SHALLOW_DEFAULTS)
    if not limits["min_diff_lines"] or diff_lines < limits["min_diff_lines"]:
        return None
    findings = len(getattr(verdict, "findings", ()) or ())
    tokens = int(getattr(usage, "tokens_out", 0) or 0)
    if not tokens:  # a usage without its output count: the verdict's own words, about 4 characters a token
        tokens = len(" ".join([str(getattr(verdict, "summary", "") or "")] + [
            str(getattr(item, "fix", "")) for item in getattr(verdict, "findings", ()) or ()])) // 4
    short = [name for name, low in (("findings", findings < limits["min_findings"]),
                                    ("rationale_tokens", tokens < limits["min_rationale_tokens"])) if low]
    if not short:
        return None
    return {"diff_lines": diff_lines, "findings": findings, "rationale_tokens": tokens, "below": short,
            "limits": limits, "model": str(getattr(usage, "model", "") or "")}


def kept_findings(findings: object) -> list[dict[str, object]]:
    kept: list[dict[str, object]] = []
    for item in list(findings or [])[:MAX_KEPT_FINDINGS] if isinstance(findings, list) else []:
        if not isinstance(item, dict):
            continue
        kept.append({key: (str(value)[:MAX_KEPT_TEXT] if isinstance(value, str) else value)
                     for key, value in item.items()
                     if key in ("id", "severity", "file", "line", "fix", "title", "field_or_claim_id", "status")
                     and (value is None or isinstance(value, str | int | float | bool))})
    return kept
