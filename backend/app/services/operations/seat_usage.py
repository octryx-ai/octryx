"""Seat usage per person: what their seat calls would have cost through the API, beside their real API cost."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import AgentPresence, DeviceJob, Project, Session, UsageEvent, User
from ...models.agent.device_job import DeviceJobEvent
from ..devices.seat_quota import turn_limit
from ..observability.agent_metrics import seat_pseudonym
from ..problems.model import iso
from .costs import SEAT_COST_SOURCE, CostQueryError

MAX_DAYS = 366
PROVIDER_LABELS = {"anthropic_seat": "Claude", "openai_codex_seat": "ChatGPT"}
EQUIVALENT_LABEL = "would cost via API (list price)"
UNPRICED_LABEL = "no list price (seat only)"


def _money(value: Any) -> float:
    return round(float(value or 0), 6)


async def _allowances(db: AsyncSession, user_ids: set[str], scope: Any) -> dict[str, list[dict[str, Any]]]:
    if not user_ids:
        return {}
    rows = (await db.execute(
        select(AgentPresence.user_id, AgentPresence.client, AgentPresence.five_hour_pct,
               AgentPresence.five_hour_resets_at, AgentPresence.seven_day_pct, AgentPresence.seven_day_resets_at,
               AgentPresence.allowance_status, AgentPresence.allowance_updated_at)
        .where(AgentPresence.user_id.in_(user_ids), AgentPresence.profile == "seat",
               AgentPresence.allowance_updated_at.is_not(None), scope(func.coalesce(AgentPresence.project_id, "")))
        .order_by(AgentPresence.allowance_updated_at.desc()))).all()
    newest: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
    for user_id, client, five, five_reset, seven, seven_reset, status, updated in rows:
        newest[user_id].setdefault(str(client or ""), {
            "client": client, "five_hour_pct": five, "five_hour_resets_at": iso(five_reset),
            "seven_day_pct": seven, "seven_day_resets_at": iso(seven_reset), "status": status,
            "updated_at": iso(updated)})
    return {user_id: list(clients.values()) for user_id, clients in newest.items()}


async def _limit_hits(db: AsyncSession, user_ids: set[str], since: datetime, scope: Any) -> dict[str, int]:
    if not user_ids:
        return {}
    rows = (await db.execute(
        select(DeviceJob.owner_user_id, DeviceJobEvent.body, DeviceJobEvent.created_at)
        .join(DeviceJob, DeviceJob.id == DeviceJobEvent.job_id)
        .where(DeviceJob.owner_user_id.in_(user_ids), DeviceJob.profile == "seat",
               DeviceJobEvent.type == "turn_finished", DeviceJobEvent.created_at >= since,
               scope(func.coalesce(DeviceJob.workspace_id, ""))))).all()
    hits: dict[str, int] = defaultdict(int)
    for user_id, body, created_at in rows:
        if turn_limit(body if isinstance(body, dict) else {}, said_at=created_at) is not None:
            hits[user_id] += 1
    return hits


async def seat_usage_report(db: AsyncSession, *, scope: Any, now: datetime, days: int) -> dict[str, Any]:
    if not 1 <= days <= MAX_DAYS:
        raise CostQueryError("days", f"days must be between 1 and {MAX_DAYS}.")
    since = now - timedelta(days=days)
    seat = UsageEvent.cost_source == SEAT_COST_SOURCE
    rows = (await db.execute(
        select(UsageEvent.user_id, UsageEvent.provider, UsageEvent.model, Session.project_id,
               func.count(), func.sum(case((seat, 1), else_=0)),
               func.sum(case((seat, UsageEvent.list_cost), else_=None)),
               func.sum(case((seat & UsageEvent.list_cost.is_(None), 1), else_=0)),
               func.sum(case((seat, None), else_=UsageEvent.cost)))
        .join(Session, Session.id == UsageEvent.session_id)
        .where(UsageEvent.created_at >= since, scope(Session.project_id))
        .group_by(UsageEvent.user_id, UsageEvent.provider, UsageEvent.model, Session.project_id))).all()
    people: dict[str, dict[str, Any]] = {}
    for user_id, provider, model, workspace_id, calls, seat_calls, listed, unpriced, api_cost in rows:
        person = people.setdefault(user_id, {
            "user_id": user_id, "api_equivalent_usd": 0.0, "api_cost_usd": 0.0, "seat_calls": 0,
            "unpriced_calls": 0, "seats": {}, "workspaces": defaultdict(lambda: {"api_equivalent_usd": 0.0,
                                                                                "api_cost_usd": 0.0})})
        person["api_cost_usd"] += float(api_cost or 0)
        workspace = person["workspaces"][workspace_id or ""]
        workspace["api_cost_usd"] += float(api_cost or 0)
        if not seat_calls:
            continue
        person["api_equivalent_usd"] += float(listed or 0)
        person["seat_calls"] += int(seat_calls)
        person["unpriced_calls"] += int(unpriced or 0)
        workspace["api_equivalent_usd"] += float(listed or 0)
        account = person["seats"].setdefault(provider, {
            "seat": seat_pseudonym(user_id, provider), "provider": provider,
            "label": PROVIDER_LABELS.get(provider, provider), "api_equivalent_usd": 0.0, "calls": 0,
            "unpriced_calls": 0, "models": defaultdict(lambda: {"api_equivalent_usd": 0.0, "calls": 0,
                                                                "unpriced_calls": 0})})
        account["api_equivalent_usd"] += float(listed or 0)
        account["calls"] += int(seat_calls)
        account["unpriced_calls"] += int(unpriced or 0)
        per_model = account["models"][model or ""]
        per_model["api_equivalent_usd"] += float(listed or 0)
        per_model["calls"] += int(seat_calls)
        per_model["unpriced_calls"] += int(unpriced or 0)
    ids = set(people)
    users = {row.id: row for row in (await db.execute(select(User.id, User.username, User.display_name)
                                                       .where(User.id.in_(ids)))).all()} if ids else {}
    workspace_ids = {wid for person in people.values() for wid in person["workspaces"] if wid}
    workspace_names = dict((await db.execute(select(Project.id, Project.name).where(
        Project.id.in_(workspace_ids)))).all()) if workspace_ids else {}
    allowances = await _allowances(db, ids, scope)
    hits = await _limit_hits(db, ids, since, scope)
    result = []
    for user_id, person in people.items():
        result.append({
            "user_id": user_id, "username": users[user_id].username if user_id in users else user_id,
            # What a person is called on every cost view (``costs._labels``: display name, else the username).
            "display_name": (users[user_id].display_name or users[user_id].username) if user_id in users else user_id,
            "api_equivalent_usd": _money(person["api_equivalent_usd"]), "api_cost_usd": _money(person["api_cost_usd"]),
            "seat_calls": person["seat_calls"], "unpriced_calls": person["unpriced_calls"],
            "seats": [{**{k: v for k, v in account.items() if k != "models"},
                       "api_equivalent_usd": _money(account["api_equivalent_usd"]),
                       "models": sorted(({"model": model, **values,
                                          "api_equivalent_usd": _money(values["api_equivalent_usd"])}
                                         for model, values in account["models"].items()),
                                        key=lambda row: -row["api_equivalent_usd"])}
                      for account in person["seats"].values()],
            "workspaces": sorted(({"workspace_id": wid or None, "name": workspace_names.get(wid) or "(none)",
                                   "api_equivalent_usd": _money(values["api_equivalent_usd"]),
                                   "api_cost_usd": _money(values["api_cost_usd"])}
                                  for wid, values in person["workspaces"].items()),
                                 key=lambda row: -row["api_equivalent_usd"]),
            "allowance": allowances.get(user_id, []), "limit_hits": hits.get(user_id, 0),
        })
    result.sort(key=lambda row: -row["api_equivalent_usd"])
    return {
        "window": {"from": iso(since), "to": iso(now), "days": days},
        "labels": {"api_equivalent_usd": EQUIVALENT_LABEL, "unpriced_calls": UNPRICED_LABEL},
        "totals": {"api_equivalent_usd": _money(sum(row["api_equivalent_usd"] for row in result)),
                   "api_cost_usd": _money(sum(row["api_cost_usd"] for row in result)),
                   "seat_calls": sum(row["seat_calls"] for row in result),
                   "unpriced_calls": sum(row["unpriced_calls"] for row in result)},
        "people": result,
    }


__all__ = ["EQUIVALENT_LABEL", "UNPRICED_LABEL", "seat_usage_report"]
