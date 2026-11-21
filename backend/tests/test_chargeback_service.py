from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from app.models import CostAllocationRule, MonthlyCostReport, Project, Session, UsageEvent, User
from app.services.chargeback import (
    _normalize_grouped_cost_projects,
    generate_monthly_cost_report,
    list_monthly_cost_reports,
    parse_report_period,
    upsert_cost_allocation_rule,
)


@pytest.mark.asyncio
async def test_generate_monthly_cost_report_applies_allocation_rules(db):
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    project = (await db.execute(select(Project).where(Project.name == "acme-orders"))).scalar_one()
    session = Session(
        id=str(uuid.uuid4()),
        user_id=admin.id,
        project_id=project.id,
        agent_type="diagnosis",
        status="active",
        metadata_={},
    )
    db.add(session)
    await db.flush()

    db.add(
        UsageEvent(
            id=str(uuid.uuid4()),
            session_id=session.id,
            user_id=admin.id,
            provider="openrouter",
            model="model-a",
            tokens_in=100,
            tokens_out=40,
            cost=1.25,
            created_at=datetime(2026, 3, 15, 12, 0, tzinfo=UTC),
        )
    )
    await db.commit()

    await upsert_cost_allocation_rule(
        db,
        rule_id=None,
        project_id=project.id,
        cost_center="ENG-42",
        percentage=100,
        valid_from=parse_report_period("2026-03")[1],
    )

    rows = await generate_monthly_cost_report(db, period="2026-03")
    assert len(rows) == 1
    assert rows[0]["project_id"] == project.id
    assert rows[0]["provider_id"] == "openrouter"
    assert rows[0]["total_cost"] == pytest.approx(1.25)
    assert rows[0]["report"]["usage_event_count"] == 1
    assert rows[0]["report"]["cost_centers"][0]["cost_center"] == "ENG-42"
    assert rows[0]["report"]["cost_centers"][0]["allocated_cost"] == pytest.approx(1.25)

    persisted = (await db.execute(select(MonthlyCostReport))).scalars().all()
    assert len(persisted) == 1


@pytest.mark.asyncio
async def test_list_monthly_cost_reports_generates_default_unallocated_rows(db):
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    project = (await db.execute(select(Project).where(Project.name == "acme-orders"))).scalar_one()
    session = Session(
        id=str(uuid.uuid4()),
        user_id=admin.id,
        project_id=project.id,
        agent_type="diagnosis",
        status="active",
        metadata_={},
    )
    db.add(session)
    await db.flush()

    db.add(
        UsageEvent(
            id=str(uuid.uuid4()),
            session_id=session.id,
            user_id=admin.id,
            provider="copilot",
            model="model-b",
            tokens_in=20,
            tokens_out=10,
            cost=0.5,
            created_at=datetime(2026, 3, 2, 8, 0, tzinfo=UTC),
        )
    )
    await db.commit()

    rows = await list_monthly_cost_reports(db, period="2026-03")
    assert len(rows) == 1
    assert rows[0]["report"]["cost_centers"][0]["cost_center"] == "unallocated"
    assert rows[0]["report"]["cost_centers"][0]["allocated_cost"] == pytest.approx(0.5)

    rules = (await db.execute(select(CostAllocationRule))).scalars().all()
    assert rules == []


@pytest.mark.asyncio
async def test_upsert_cost_allocation_rule_rejects_totals_above_100_for_same_date(db):
    project = (await db.execute(select(Project).where(Project.name == "acme-orders"))).scalar_one()
    valid_from = parse_report_period("2026-03")[1]

    await upsert_cost_allocation_rule(
        db,
        rule_id=None,
        project_id=project.id,
        cost_center="ENG",
        percentage=60,
        valid_from=valid_from,
    )

    with pytest.raises(Exception) as exc_info:
        await upsert_cost_allocation_rule(
            db,
            rule_id=None,
            project_id=project.id,
            cost_center="OPS",
            percentage=50,
            valid_from=valid_from,
        )

    assert "exceeds 100" in str(exc_info.value)


def test_normalize_grouped_cost_projects_coalesces_orphaned_projects():
    grouped = {
        ("project-a", "openrouter"): {"total_cost": 1.25, "usage_events": 2, "cost_centers": {}},
        ("orphaned-project", "openrouter"): {"total_cost": 2.5, "usage_events": 3, "cost_centers": {}},
        (None, "copilot"): {"total_cost": 0.5, "usage_events": 1, "cost_centers": {}},
    }

    normalized = _normalize_grouped_cost_projects(grouped, valid_project_ids={"project-a"})

    assert ("project-a", "openrouter") in normalized
    assert (None, "openrouter") in normalized
    assert normalized[(None, "openrouter")]["total_cost"] == pytest.approx(2.5)
    assert normalized[(None, "openrouter")]["usage_events"] == 3
    assert normalized[(None, "copilot")]["total_cost"] == pytest.approx(0.5)
