from __future__ import annotations

from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import (
    ConnectorWatcher,
    ConnectorWatcherEvent,
    ConnectorWatcherRule,
    ConnectorWatcherRuleDecision,
    User,
)
from .connector_watcher_rule_logic import (
    _action_result,
    _actions,
    _audit,
    _bounded_int,
    _conditions,
    _decision,
    _event_context,
    _event_context_from_payload,
    _rule_matches_context,
    serialize_connector_watcher_rule,
    serialize_connector_watcher_rule_decision,
)
from .connector_watcher_scope import WatcherScope, require_record, require_write_scope, scope_filter
from .secure_work.jira_values import blank_to_none, object_value, string_list


async def list_connector_watcher_rules(
    db: AsyncSession,
    *,
    scope: WatcherScope,
    project_id: str | None = None,
    include_inactive: bool = False,
) -> list[dict[str, Any]]:
    """The rules of ``scope`` (``connector_watcher_scope``); the caller has checked a named ``project_id``."""
    stmt = select(ConnectorWatcherRule)
    condition = scope_filter(ConnectorWatcherRule.project_id, scope, project_id)
    if condition is not None:
        stmt = stmt.where(condition)
    if not include_inactive:
        stmt = stmt.where(ConnectorWatcherRule.is_active.is_(True))
    rows = (
        (await db.execute(stmt.order_by(ConnectorWatcherRule.priority.asc(), ConnectorWatcherRule.name.asc())))
        .scalars()
        .all()
    )
    return [serialize_connector_watcher_rule(row) for row in rows]


async def create_connector_watcher_rule(
    db: AsyncSession,
    *,
    current_user: User,
    scope: WatcherScope,
    payload: dict[str, Any],
) -> dict[str, Any]:
    normalized = await _normalized_rule_payload(db, current_user, scope, payload)
    rule = ConnectorWatcherRule(**normalized, created_by=current_user.id, updated_by=current_user.id)
    db.add(rule)
    db.add(
        _audit(
            current_user.id,
            "connector_watcher_rule.created",
            "connector_watcher_rule",
            rule.id,
            {"name": rule.name},
        )
    )
    await db.flush()
    return serialize_connector_watcher_rule(rule)


async def update_connector_watcher_rule(
    db: AsyncSession,
    *,
    rule_id: str,
    current_user: User,
    scope: WatcherScope,
    payload: dict[str, Any],
) -> dict[str, Any]:
    rule = await _get_rule(db, rule_id, scope=scope)
    normalized = await _normalized_rule_payload(db, current_user, scope, payload)
    for key, value in normalized.items():
        setattr(rule, key, value)
    rule.updated_by = current_user.id
    db.add(
        _audit(
            current_user.id,
            "connector_watcher_rule.updated",
            "connector_watcher_rule",
            rule.id,
            {"name": rule.name},
        )
    )
    await db.flush()
    return serialize_connector_watcher_rule(rule)


async def test_connector_watcher_rule(
    db: AsyncSession,
    *,
    rule_id: str,
    scope: WatcherScope,
    payload: dict[str, Any],
) -> dict[str, Any]:
    rule = await _get_rule(db, rule_id, scope=scope)
    context = _event_context_from_payload(payload)
    matched, reasons = _rule_matches_context(rule, context)
    actions = _actions(rule.actions_json)
    return {
        "rule": serialize_connector_watcher_rule(rule),
        "matched": matched,
        "decision": _decision(actions) if matched else "not_matched",
        "reasons": reasons,
        "actions": actions if matched else [],
        "action_results": [_action_result(action) for action in actions] if matched else [],
    }


async def evaluate_connector_watcher_rules_for_event(
    db: AsyncSession,
    *,
    watcher: ConnectorWatcher,
    event: ConnectorWatcherEvent,
) -> list[dict[str, Any]]:
    stmt = select(ConnectorWatcherRule).where(ConnectorWatcherRule.is_active.is_(True))
    stmt = stmt.where(
        (ConnectorWatcherRule.project_id == watcher.project_id) | (ConnectorWatcherRule.project_id.is_(None))
    )
    stmt = stmt.order_by(ConnectorWatcherRule.priority.asc(), ConnectorWatcherRule.name.asc())
    rules = (await db.execute(stmt)).scalars().all()
    context = _event_context(watcher, event)
    decisions: list[ConnectorWatcherRuleDecision] = []
    summaries: list[dict[str, Any]] = []
    for rule in rules:
        matched, reasons = _rule_matches_context(rule, context)
        if not matched:
            continue
        actions = _actions(rule.actions_json)
        decision = _decision(actions)
        results = [_action_result(action) for action in actions]
        row = ConnectorWatcherRuleDecision(
            rule_id=rule.id,
            event_id=event.id,
            watcher_id=watcher.id,
            project_id=watcher.project_id,
            decision=decision,
            matched=True,
            actions_json=actions,
            reasons_json=reasons,
            action_results_json=results,
            audit_json={
                "connector_name": watcher.connector_name,
                "connector_instance": watcher.connector_instance,
                "event_type": event.event_type,
                "external_id": event.external_id,
            },
        )
        db.add(row)
        db.add(
            _audit(
                rule.created_by,
                "connector_watcher_rule.decision",
                "connector_watcher_event",
                event.id,
                row.audit_json,
            )
        )
        decisions.append(row)
    await db.flush()
    for row in decisions:
        summaries.append(serialize_connector_watcher_rule_decision(row))
    event.processing_result_json = {
        **dict(event.processing_result_json or {}),
        "rule_decisions": summaries,
        "rule_decision_count": len(summaries),
    }
    return summaries


async def list_connector_watcher_rule_decisions(
    db: AsyncSession,
    *,
    scope: WatcherScope,
    event_id: str | None = None,
    rule_id: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    stmt = select(ConnectorWatcherRuleDecision)
    condition = scope_filter(ConnectorWatcherRuleDecision.project_id, scope, None)
    if condition is not None:
        stmt = stmt.where(condition)
    if event_id:
        stmt = stmt.where(ConnectorWatcherRuleDecision.event_id == event_id)
    if rule_id:
        stmt = stmt.where(ConnectorWatcherRuleDecision.rule_id == rule_id)
    rows = (
        (await db.execute(stmt.order_by(ConnectorWatcherRuleDecision.created_at.desc()).limit(max(1, min(limit, 500)))))
        .scalars()
        .all()
    )
    return [serialize_connector_watcher_rule_decision(row) for row in rows]


async def _normalized_rule_payload(
    db: AsyncSession, current_user: User, scope: WatcherScope, payload: dict[str, Any]
) -> dict[str, Any]:
    project_id = blank_to_none(payload.get("project_id"))
    await require_write_scope(db, current_user, scope, project_id)
    name = str(payload.get("name") or "").strip()
    if not name:
        raise HTTPException(status_code=422, detail="name is required")
    actions = _actions(payload.get("actions"))
    if not actions:
        actions = [{"type": "audit_only"}]
    return {
        "project_id": project_id,
        "name": name[:220],
        "description": blank_to_none(payload.get("description")),
        "connector_name": blank_to_none(payload.get("connector_name")),
        "connector_instance": blank_to_none(payload.get("connector_instance")),
        "event_types_json": string_list(payload.get("event_types")),
        "conditions_json": _conditions(payload.get("conditions")),
        "actions_json": actions,
        "enforcement_json": object_value(payload.get("enforcement")),
        "override_roles_json": string_list(payload.get("override_roles")),
        "rate_limit_json": object_value(payload.get("rate_limit")),
        "priority": _bounded_int(payload.get("priority"), default=100, low=0, high=10000),
        "status": str(payload.get("status") or "draft").strip()[:80],
        "is_active": bool(payload.get("is_active", True)),
    }


async def _get_rule(db: AsyncSession, rule_id: str, *, scope: WatcherScope) -> ConnectorWatcherRule:
    """The rule, when it exists in ``scope``; a foreign one is the 404 of a missing one."""
    return require_record(await db.get(ConnectorWatcherRule, rule_id), scope, "Connector watcher rule not found")
