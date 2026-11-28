from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.models import BudgetAlert, BudgetPolicy, Project, Session, UsageEvent, User
from app.services.budget import list_budget_alert_surface


@pytest.mark.asyncio
async def test_list_budget_alert_surface_separates_history_from_active_blocks(db, auth_user):
    project = (await db.execute(select(Project).where(Project.name == "acme-orders"))).scalar_one()

    history_policy = BudgetPolicy(
        id=str(uuid.uuid4()),
        name="History only",
        user_id=auth_user.id,
        daily_request_limit=5,
        warn_at_percent=80,
        block_at_percent=100,
        is_active=True,
    )
    active_policy = BudgetPolicy(
        id=str(uuid.uuid4()),
        name="Currently blocked",
        user_id=auth_user.id,
        daily_request_limit=1,
        warn_at_percent=80,
        block_at_percent=100,
        is_active=True,
    )
    db.add_all([history_policy, active_policy])

    history_session = Session(
        id=str(uuid.uuid4()),
        user_id=auth_user.id,
        project_id=project.id,
        agent_type="chat",
        status="completed",
        metadata_={},
    )
    active_session = Session(
        id=str(uuid.uuid4()),
        user_id=auth_user.id,
        project_id=project.id,
        agent_type="chat",
        status="active",
        metadata_={},
    )
    db.add_all([history_session, active_session])
    await db.flush()

    db.add(
        BudgetAlert(
            id=str(uuid.uuid4()),
            policy_id=history_policy.id,
            user_id=auth_user.id,
            project_id=project.id,
            session_id=history_session.id,
            metric_name="requests",
            threshold_level="block",
            current_value=5,
            limit_value=5,
            percent_used=100,
            details={"policy_name": history_policy.name},
            message="Historical block event",
            created_at=datetime.now(UTC) - timedelta(days=1),
        )
    )
    db.add(
        UsageEvent(
            id=str(uuid.uuid4()),
            session_id=active_session.id,
            user_id=auth_user.id,
            provider="openrouter",
            model="gpt-test",
            tokens_in=5,
            tokens_out=1,
            cost=0.1,
            created_at=datetime.now(UTC),
        )
    )
    await db.commit()

    payload = await list_budget_alert_surface(db, limit=10)

    assert payload["summary"] == {"alertCount": 1, "activeBlockCount": 1}
    assert [alert["policyId"] for alert in payload["alerts"]] == [history_policy.id]
    assert payload["alerts"][0]["thresholdLevel"] == "block"
    assert payload["alerts"][0]["message"] == "Historical block event"
    assert [entry["policyId"] for entry in payload["activeBlocks"]] == [active_policy.id]
    assert payload["activeBlocks"][0]["metricName"] == "requests"
    assert payload["activeBlocks"][0]["percentUsed"] == 100


@pytest.mark.asyncio
async def test_admin_panel_budget_alerts_surface_returns_history_and_active_blocks(admin_client, db):
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    project = (await db.execute(select(Project).where(Project.name == "acme-orders"))).scalar_one()

    policy = BudgetPolicy(
        id=str(uuid.uuid4()),
        name="Panel budget",
        user_id=admin.id,
        daily_request_limit=1,
        warn_at_percent=80,
        block_at_percent=100,
        is_active=True,
    )
    session = Session(
        id=str(uuid.uuid4()),
        user_id=admin.id,
        project_id=project.id,
        agent_type="chat",
        status="active",
        metadata_={},
    )
    db.add_all([policy, session])
    await db.flush()

    alert = BudgetAlert(
        id=str(uuid.uuid4()),
        policy_id=policy.id,
        user_id=admin.id,
        project_id=project.id,
        session_id=session.id,
        metric_name="requests",
        threshold_level="warning",
        current_value=1,
        limit_value=1,
        percent_used=100,
        details={"policy_name": policy.name},
        message="Warning persisted for operators",
        created_at=datetime.now(UTC),
    )
    usage = UsageEvent(
        id=str(uuid.uuid4()),
        session_id=session.id,
        user_id=admin.id,
        provider="openrouter",
        model="gpt-test",
        tokens_in=1,
        tokens_out=0,
        cost=0.0,
        created_at=datetime.now(UTC),
    )
    db.add_all([alert, usage])
    await db.commit()

    response = await admin_client.get("/admin/chat/api/panel/budget-alerts?limit=10")
    assert response.status_code == 200

    payload = response.json()
    assert payload["summary"] == {"alertCount": 1, "activeBlockCount": 1}
    assert payload["alerts"][0]["policyId"] == policy.id
    assert payload["alerts"][0]["thresholdLevel"] == "warning"
    assert payload["activeBlocks"][0]["policyId"] == policy.id
    assert payload["activeBlocks"][0]["blockAtPercent"] == 100
