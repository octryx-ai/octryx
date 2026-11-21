"""Observability → Overview (O7): what needs my attention, at a glance.

Built only from the other Observability read models (Health, Usage & costs, Decisions) plus the pending approvals and
clarifications they already show: no data source of its own. Every attention item has a severity (with a word,
never colour alone), a one-line cause, its age and exactly one link into the screen that owns the fix. Nothing is
decided on the Overview.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import Approval, ClarificationQuestion, PolicyDecisionLog, Session
from ...time_utils import ensure_utc, utc_now
from ..decisions.timeline import decisions_today
from .health_read_model import health_overview
from .usage_read_model import usage_overview

CONNECTION_GRACE = timedelta(minutes=15)
REVIEW_STALE = timedelta(hours=24)
SESSION_IDLE = timedelta(hours=1)
CLARIFICATION_STALE = timedelta(hours=24)
BUDGET_WARN_PERCENT = 80
DANGER, ATTENTION = "danger", "attention"


def _age(since: Any, now: datetime) -> str:
    if since is None:
        return ""
    value = since if isinstance(since, datetime) else datetime.fromisoformat(str(since))
    minutes = int((ensure_utc(now) - ensure_utc(value)).total_seconds() // 60)
    if minutes < 60:
        return f"{max(minutes, 0)} min"
    if minutes < 48 * 60:
        return f"{minutes // 60} h {minutes % 60:02d} min" if minutes < 6 * 60 else f"{minutes // 60} h"
    return f"{minutes // (24 * 60)} d"


def _item(severity: str, label: str, title: str, cause: str, age: str, action: str, link: dict[str, str]) -> dict:
    return {"severity": severity, "label": label, "title": title, "cause": cause, "age": age, "action": action,
            "link": link}


def _health_items(health: dict[str, Any], now: datetime) -> list[dict[str, Any]]:
    items = []
    for group in health["groups"]:
        for row in group["rows"]:
            if row["status"] != "failing":
                continue
            since = row.get("since")
            if group["key"] == "connections" and since and ensure_utc(now) - ensure_utc(
                    datetime.fromisoformat(since)) < CONNECTION_GRACE:
                continue
            link = row.get("link") or {"tab": "observabilityHealth", "label": "Observability → Health"}
            items.append(_item(DANGER, "✕ failing", f"{row['component']} failing", row["detail"] or "Failing check.",
                               _age(since, now) or "now", f"Open {link['label'].split(' → ')[-1]}", link))
        if group["key"] == "background":
            for row in group["rows"]:
                if row["component"].startswith("Dead letters") and row["status"] != "ok":
                    items.append(_item(ATTENTION, "! waiting", f"{row['detail']} dead letters in 7 days",
                                       "Background actions failed and wait for a retry or a decision.", "7 d",
                                       "Open actions", row["link"]))
    return items


async def _waiting_items(db: AsyncSession, now: datetime) -> list[dict[str, Any]]:
    items = []
    reviews = (await db.execute(select(func.count(), func.min(Approval.created_at)).where(
        Approval.status == "pending", Approval.session_id.is_(None), Approval.task_run_id.is_(None),
        Approval.created_at < now - REVIEW_STALE))).one()
    if reviews[0]:
        items.append(_item(ATTENTION, "! waiting", f"{reviews[0]} governance review(s) wait for a second reviewer",
                           "Pending for more than 24 hours; under four-eyes the requester cannot approve.",
                           _age(reviews[1], now), "Show in Decisions",
                           {"tab": "observabilityDecisions", "label": "Observability → Decisions"}))
    idle = (await db.execute(select(func.count(), func.min(Approval.created_at)).join(
        Session, Session.id == Approval.session_id).where(
        Approval.status == "pending",
        func.coalesce(Session.last_activity_at, Session.started_at) < now - SESSION_IDLE))).one()
    if idle[0]:
        items.append(_item(ATTENTION, "! waiting", f"{idle[0]} approval(s) wait on sessions without activity",
                           "They expire automatically 24 hours after the session's last activity.",
                           _age(idle[1], now), "Show in Decisions",
                           {"tab": "observabilityDecisions", "label": "Observability → Decisions"}))
    questions = (await db.execute(select(func.count(), func.min(ClarificationQuestion.created_at)).where(
        ClarificationQuestion.status == "open",
        ClarificationQuestion.created_at < now - CLARIFICATION_STALE))).one()
    if questions[0]:
        items.append(_item(ATTENTION, "! waiting", f"{questions[0]} clarification(s) unanswered for more than a day",
                           "The run waits for the requester's answer in the chat thread.", _age(questions[1], now),
                           "Open runs", {"tab": "observabilityRuns", "label": "Observability → Runs"}))
    # Workflow runs that wait for a person.
    from ..workflow_runs.attention import RUNS_LINK, attention_counts

    for kind, count, oldest, cause in await attention_counts(db, now):
        title = f"{count} workflow run(s) paused" if kind == "paused" else f"{count} workflow run(s) waiting > 1 day"
        items.append(_item(ATTENTION, "! waiting", title, cause, _age(oldest, now), "Open workflow runs", RUNS_LINK))
    dropped = int((await db.execute(select(func.count()).select_from(PolicyDecisionLog).where(
        PolicyDecisionLog.outcome == "dropped",
        PolicyDecisionLog.created_at >= now - timedelta(days=1)))).scalar() or 0)
    if dropped:
        items.append(_item(DANGER, "✕ failing", "Decision records were dropped",
                           "The decision buffer overflowed; some decisions are missing from the timeline.", "1 d",
                           "Open Decisions", {"tab": "observabilityDecisions", "label": "Observability → Decisions"}))
    return items


def _cost_items(usage: dict[str, Any]) -> list[dict[str, Any]]:
    items = []
    unpriced = [row for row in usage["by_model"] if row["pricing"] == "unpriced"]
    if unpriced:
        names = ", ".join(row["model"] for row in unpriced[:3])
        tiles = usage["tiles"]
        share = round(tiles["unpriced_tokens"] / tiles["platform_billed_tokens"] * 100) if tiles[
            "platform_billed_tokens"] else 0
        effect = ("runs on it are refused while a cost cap is active" if usage["unpriced_policy"] == "block"
                  else "no cost cap can stop it")
        items.append(_item(ATTENTION, "! cost", "Unpriced model in use",
                           f"{names} has no price: {share} % of tokens this month count as $0 and {effect}.",
                           "this month", "Set a price", {"tab": "modelCatalog", "label": "Runtime → Model catalog"}))
    for budget in usage["budgets"]:
        if (budget.get("percent") or 0) >= BUDGET_WARN_PERCENT:
            items.append(_item(ATTENTION, "! cost", f"{budget['limit']} budget at {budget['percent']} %",
                               f"{budget['scope']}: {budget['used']} of {budget['cap']} USD.", "this month",
                               "Open limits", {"tab": "runtimeLimits", "label": "Runtime → Limits & budgets"}))
    return items


def _strip(health: dict[str, Any]) -> list[dict[str, Any]]:
    order = ("failing", "degraded", "unknown", "ok", "disabled")
    strip = []
    for group in health["groups"]:
        statuses = [row["status"] for row in group["rows"]]
        worst = next((status for status in order if status in statuses), "unknown")
        counts = {status: statuses.count(status) for status in order if statuses.count(status)}
        first = next((row for row in group["rows"] if row["status"] == worst), None)
        strip.append({"key": group["key"], "label": group["label"].split(" (")[0], "status": worst, "counts": counts,
                      "detail": (f"{first['component']}" + (f" · {first['detail']}" if first and first["detail"]
                                                             and worst != "ok" else "")) if first else "–"})
    return strip


async def overview(db: AsyncSession, *, checks: dict[str, dict[str, Any]]) -> dict[str, Any]:
    now = utc_now()
    health = await health_overview(db, checks=checks)
    usage = await usage_overview(db, window="month")
    today = await decisions_today(db)
    attention = [*_health_items(health, now), *await _waiting_items(db, now), *_cost_items(usage)]
    rank = {DANGER: 0, ATTENTION: 1}
    attention.sort(key=lambda item: rank.get(item["severity"], 2))
    return {
        "checked_at": health["checked_at"],
        "attention": attention,
        "health": {"summary": health["summary"], "strip": _strip(health)},
        "spend": {"month_spend": usage["tiles"]["spend"], "priced_coverage": usage["tiles"]["priced_coverage"],
                  "since": usage["since"]},
        "decisions_today": today,
    }


__all__ = ["overview"]
