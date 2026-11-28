"""Observability Overview: what needs attention, each item with one link to its owner."""

from __future__ import annotations

import uuid
from datetime import timedelta
from decimal import Decimal

import pytest

from app.models import Approval, ConnectorHealth, ConnectorHealthLog, UsageEvent
from app.services.observability.overview_read_model import overview
from app.time_utils import utc_now
from tests.observability_support import admin_user, call_as, session_for, user_with_role


@pytest.mark.asyncio
async def test_overview_lists_failing_waiting_and_cost_items_with_one_link_each(db):
    now = utc_now()
    admin = await admin_user(db)
    name = f"servicenow-{uuid.uuid4().hex[:6]}"
    recent = f"jira-{uuid.uuid4().hex[:6]}"
    db.add(ConnectorHealth(connector_name=name, project_id="", status="error", error="invalid_client",
                           last_checked=now))
    db.add(ConnectorHealthLog(connector_name=name, project_id="", status="error", checked_at=now - timedelta(hours=3)))
    # Failing for only 5 minutes: not yet an attention item (15 min grace).
    db.add(ConnectorHealth(connector_name=recent, project_id="", status="error", last_checked=now))
    db.add(ConnectorHealthLog(connector_name=recent, project_id="", status="error", checked_at=now - timedelta(minutes=5)))
    db.add(Approval(requested_by=admin.id, action="policy_set.publish:x", status="pending",
                    created_at=now - timedelta(days=2)))
    session = await session_for(db, admin)
    db.add(UsageEvent(session_id=session.id, user_id=admin.id, provider="bedrock", model="unpriced-model",
                      tokens_in=1000, cost=Decimal("0"), cost_status="missing_pricing"))
    await db.commit()

    payload = await overview(db, checks={"database": {"status": "ok"}}, viewer_id=admin.id)

    titles = [item["title"] for item in payload["attention"]]
    assert f"{name} · global failing" in titles
    assert f"{recent} · global failing" not in titles
    assert any("governance review" in title for title in titles)
    assert "Unpriced model in use" in titles
    assert payload["attention"][0]["severity"] == "danger", "failing items come first"
    assert all(item["link"].get("tab") or item["link"].get("href") for item in payload["attention"])
    assert {entry["key"] for entry in payload["health"]["strip"]} == {
        "platform", "connections", "syncs", "providers", "background"}
    assert next(entry for entry in payload["health"]["strip"] if entry["key"] == "connections")["status"] == "failing"
    assert payload["decisions_today"]["total"] >= 0 and "month_spend" in payload["spend"]


@pytest.mark.asyncio
async def test_overview_route_is_admin_only(client, db):
    admin = await admin_user(db)
    viewer = await user_with_role(db, "viewer")
    assert (await call_as(client, "GET", "/api/v1/observability/overview", viewer)).status_code == 403
    response = await call_as(client, "GET", "/api/v1/observability/overview", admin)
    assert response.status_code == 200 and "attention" in response.json()
