from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.models import (
    AnalyticsDaily,
    Approval,
    Message,
    MessageFeedback,
    Project,
    ReportExport,
    Session,
    ToolCall,
    UsageEvent,
    User,
)
from app.services.analytics.service import (
    aggregate_analytics_for_date,
    process_pending_report_exports,
)
from app.time_utils import utc_now
from tests.conftest import ADMIN_PASSWORD


async def _seed_completed_session(db, admin: User, project: Project, started_at: datetime) -> tuple[Session, Message]:
    session = Session(
        id=str(uuid.uuid4()),
        user_id=admin.id,
        project_id=project.id,
        status="active",
        metadata_={"run_status": "completed", "run_completion_reason": "completed"},
        started_at=started_at,
        ended_at=started_at + timedelta(minutes=9),
    )
    db.add(session)
    await db.flush()

    message = Message(
        id=str(uuid.uuid4()),
        session_id=session.id,
        role="assistant",
        content="done",
        created_at=started_at + timedelta(minutes=9),
    )
    db.add(message)
    return session, message


def _add_knowledge_usage_and_approval(db, admin: User, session: Session, started_at: datetime) -> None:
    db.add(
        ToolCall(
            id=str(uuid.uuid4()),
            session_id=session.id,
            tool_name="knowledge_search",
            result={"evidence": [{"text": "entry-1"}]},
            status="success",
            created_at=started_at + timedelta(minutes=2),
        )
    )
    db.add(
        UsageEvent(
            id=str(uuid.uuid4()),
            session_id=session.id,
            user_id=admin.id,
            provider="openrouter",
            model="gpt-test",
            tokens_in=120,
            tokens_out=80,
            cost=0.42,
            created_at=started_at + timedelta(minutes=3),
        )
    )
    db.add(
        Approval(
            id=str(uuid.uuid4()),
            session_id=session.id,
            requested_by=admin.id,
            approved_by=admin.id,
            action="bash",
            reason="Need approval",
            status="approved",
            created_at=started_at + timedelta(minutes=4),
        )
    )


def _add_memory_read_and_feedback(db, admin: User, session: Session, message: Message, started_at: datetime) -> None:
    # Memory reads are the governed lobe's recall calls.
    db.add(
        ToolCall(
            id=str(uuid.uuid4()),
            session_id=session.id,
            tool_name="memory_recall",
            result={"state": "ok", "memories": []},
            status="success",
            created_at=started_at + timedelta(minutes=5),
        )
    )
    db.add(
        MessageFeedback(
            id=str(uuid.uuid4()),
            message_id=message.id,
            user_id=admin.id,
            rating=1,
            comment="good",
            created_at=started_at + timedelta(minutes=10),
        )
    )


def _assert_daily_metrics(row: AnalyticsDaily) -> None:
    assert row.sessions_total == 1
    assert row.sessions_completed == 1
    assert row.sessions_failed == 0
    assert row.tool_calls_total == 2
    assert row.tool_calls_success == 2
    assert row.approvals_requested == 1
    assert row.approvals_approved == 1
    assert float(row.total_cost) == pytest.approx(0.42)
    assert row.total_tokens_in == 120
    assert row.total_tokens_out == 80
    assert row.knowledge_queries == 1
    assert row.knowledge_hits == 1
    assert row.memory_reads == 1
    assert row.memory_writes == 0
    assert row.positive_feedback == 1
    assert row.cost_by_provider["openrouter"] == pytest.approx(0.42)


@pytest.mark.asyncio
async def test_aggregate_analytics_for_date_persists_metrics(db):
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    project = (await db.execute(select(Project).where(Project.name == "acme-orders"))).scalar_one()
    now = utc_now()
    started_at = datetime(now.year, now.month, now.day, 12, 0, tzinfo=UTC)

    session, message = await _seed_completed_session(db, admin, project, started_at)

    _add_knowledge_usage_and_approval(db, admin, session, started_at)
    _add_memory_read_and_feedback(db, admin, session, message, started_at)
    await db.commit()

    affected = await aggregate_analytics_for_date(db, target_date=started_at.date())
    assert affected >= 1

    row = (
        await db.execute(
            select(AnalyticsDaily).where(
                AnalyticsDaily.project_id == project.id,
                AnalyticsDaily.team_id.is_(None),
                AnalyticsDaily.date == started_at.date(),
            )
        )
    ).scalar_one()
    _assert_daily_metrics(row)


def _add_analytics_daily_row(db, project: Project, target_date) -> None:
    db.add(
        AnalyticsDaily(
            id=str(uuid.uuid4()),
            project_id=project.id,
            team_id=None,
            date=target_date,
            sessions_total=2,
            sessions_completed=1,
            sessions_failed=1,
            tool_calls_total=3,
            tool_calls_success=2,
            tool_calls_failed=1,
            approvals_requested=1,
            approvals_approved=1,
            total_cost=0.55,
            total_tokens_in=200,
            total_tokens_out=140,
            knowledge_queries=2,
            knowledge_hits=1,
            positive_feedback=1,
            negative_feedback=0,
        )
    )


async def _request_api_and_panel_exports(client, auth_headers, project: Project, target_date):
    create_resp = await client.post(
        "/api/v1/reports/export",
        headers=auth_headers,
        json={
            "report_type": "cost_summary",
            "format": "csv",
            "parameters": {
                "project_id": project.id,
                "date_from": target_date.isoformat(),
                "date_to": target_date.isoformat(),
            },
        },
    )
    assert create_resp.status_code == 200, create_resp.text
    report_id = create_resp.json()["id"]

    login_resp = await client.post("/admin/login", data={"username": "admin", "password": ADMIN_PASSWORD})
    assert login_resp.status_code == 303

    panel_create_resp = await client.post(
        "/admin/chat/api/panel/reports/export",
        json={
            "report_type": "knowledge_coverage",
            "format": "json",
            "parameters": {"project_id": project.id},
        },
    )
    assert panel_create_resp.status_code == 200, panel_create_resp.text
    return report_id, panel_create_resp


@pytest.mark.asyncio
async def test_report_exports_api_and_panel_flow(client, auth_headers, db, monkeypatch, tmp_path):
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    project = (await db.execute(select(Project).where(Project.name == "acme-orders"))).scalar_one()
    target_date = utc_now().date()
    _add_analytics_daily_row(db, project, target_date)
    await db.commit()

    monkeypatch.setattr("app.services.analytics.service.REPORT_EXPORT_DIR", tmp_path)

    analytics_resp = await client.get("/api/v1/analytics/daily", headers=auth_headers)
    assert analytics_resp.status_code == 200
    assert analytics_resp.json()

    report_id, panel_create_resp = await _request_api_and_panel_exports(client, auth_headers, project, target_date)

    processed = await process_pending_report_exports(db)
    assert processed >= 2

    list_resp = await client.get("/api/v1/reports/export", headers=auth_headers)
    assert list_resp.status_code == 200
    assert any(item["id"] == report_id and item["status"] == "completed" for item in list_resp.json())

    download_resp = await client.get(f"/api/v1/reports/export/{report_id}/download", headers=auth_headers)
    assert download_resp.status_code == 200
    assert "text/csv" in download_resp.headers["content-type"]
    assert b"total_cost" in download_resp.content

    panel_daily_resp = await client.get("/admin/chat/api/panel/analytics/daily")
    assert panel_daily_resp.status_code == 200
    assert any(item["project_id"] == project.id for item in panel_daily_resp.json())

    panel_exports_resp = await client.get("/admin/chat/api/panel/report-exports")
    assert panel_exports_resp.status_code == 200
    panel_export_id = panel_create_resp.json()["id"]
    assert any(item["id"] == panel_export_id for item in panel_exports_resp.json())

    panel_download_resp = await client.get(f"/admin/chat/api/panel/report-exports/{panel_export_id}/download")
    assert panel_download_resp.status_code == 200
    assert panel_download_resp.headers["content-type"].startswith("application/json")

    stored_exports = (await db.execute(select(ReportExport).where(ReportExport.created_by == admin.id))).scalars().all()
    assert len(stored_exports) >= 2


def test_analytics_package_exports_its_service() -> None:
    import app.services.analytics as package_module
    import app.services.analytics.service as service_module

    assert package_module.AnalyticsWorker is service_module.AnalyticsWorker
    assert package_module.aggregate_due_analytics is service_module.aggregate_due_analytics
    assert package_module.process_pending_report_exports is service_module.process_pending_report_exports
