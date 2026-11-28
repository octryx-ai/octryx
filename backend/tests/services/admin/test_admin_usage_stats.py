from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from app.models import Project, Session, UsageEvent
from app.services.admin.panel._admin_misc_core import channel_stats, usage_stats


def _diagnosis_session(admin, project, metadata, started_at):
    return Session(
        id=str(uuid.uuid4()),
        user_id=admin.id,
        project_id=project.id,
        agent_type="diagnosis",
        status="active",
        metadata_=metadata,
        started_at=started_at,
    )


def _usage_event(session_id, admin, tokens_in, tokens_out, cost, created_at):
    return UsageEvent(
        id=str(uuid.uuid4()),
        session_id=session_id,
        user_id=admin.id,
        provider="openrouter",
        model="gpt-test",
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        cost=cost,
        created_at=created_at,
    )


async def _seed_sessions_with_usage(db, admin, project):
    direct_session = _diagnosis_session(
        admin,
        project,
        {"message_count": 5, "total_tokens_in": 9999, "total_tokens_out": 8888, "total_cost": 99.0},
        datetime(2026, 4, 20, 9, 0, tzinfo=UTC),
    )
    channel_session = _diagnosis_session(
        admin,
        project,
        {
            "channel": "slack",
            "channel_id": "42",
            "message_count": 3,
            "total_tokens_in": 7777,
            "total_tokens_out": 6666,
            "total_cost": 77.0,
        },
        datetime(2026, 4, 20, 10, 0, tzinfo=UTC),
    )
    stale_session = _diagnosis_session(
        admin,
        project,
        {
            "channel": "teams",
            "channel_id": "84",
            "message_count": 9,
            "total_tokens_in": 5555,
            "total_tokens_out": 4444,
            "total_cost": 55.0,
        },
        datetime(2026, 4, 20, 11, 0, tzinfo=UTC),
    )
    db.add_all([direct_session, channel_session, stale_session])
    await db.flush()

    db.add_all(
        [
            _usage_event(direct_session.id, admin, 100, 40, 1.25, datetime(2026, 4, 20, 9, 5, tzinfo=UTC)),
            _usage_event(channel_session.id, admin, 20, 10, 0.5, datetime(2026, 4, 20, 10, 5, tzinfo=UTC)),
            _usage_event(channel_session.id, admin, 5, 1, 0.125, datetime(2026, 4, 20, 10, 10, tzinfo=UTC)),
        ]
    )
    await db.commit()


@pytest.mark.asyncio
async def test_usage_stats_uses_usage_events_for_cost_and_tokens(db, auth_user):
    project = (await db.execute(select(Project).where(Project.name == "acme-orders"))).scalar_one()
    await _seed_sessions_with_usage(db, auth_user, project)

    payload = await usage_stats(db)

    assert payload["totals"] == {
        "total_cost": pytest.approx(1.875),
        "total_tokens_in": 125,
        "total_tokens_out": 51,
        "total_sessions": 2,
    }
    assert payload["by_user"] == [
        {
            "user_id": auth_user.id,
            "username": "admin",
            "sessions": 2,
            "message_count": 8,
            "total_tokens_in": 125,
            "total_tokens_out": 51,
            "total_cost": pytest.approx(1.875),
        }
    ]
    assert payload["by_channel"] == [
        {
            "channel": "direct",
            "sessions": 1,
            "message_count": 5,
            "total_cost": pytest.approx(1.25),
        },
        {
            "channel": "slack",
            "sessions": 1,
            "message_count": 3,
            "total_cost": pytest.approx(0.625),
        },
    ]


@pytest.mark.asyncio
async def test_channel_stats_uses_usage_events_for_channel_totals(db, auth_user):
    project = (await db.execute(select(Project).where(Project.name == "acme-orders"))).scalar_one()

    tracked_session = Session(
        id=str(uuid.uuid4()),
        user_id=auth_user.id,
        project_id=project.id,
        agent_type="diagnosis",
        status="active",
        metadata_={
            "channel": "slack",
            "channel_id": "7",
            "message_count": 4,
            "total_tokens_in": 999,
            "total_cost": 99.0,
        },
        started_at=datetime(2026, 4, 20, 12, 0, tzinfo=UTC),
    )
    ignored_session = Session(
        id=str(uuid.uuid4()),
        user_id=auth_user.id,
        project_id=project.id,
        agent_type="diagnosis",
        status="active",
        metadata_={"channel": "slack", "channel_id": "8", "message_count": 2},
        started_at=datetime(2026, 4, 20, 12, 5, tzinfo=UTC),
    )
    db.add_all([tracked_session, ignored_session])
    await db.flush()

    db.add(
        UsageEvent(
            id=str(uuid.uuid4()),
            session_id=tracked_session.id,
            user_id=auth_user.id,
            provider="openrouter",
            model="gpt-test",
            tokens_in=30,
            tokens_out=12,
            cost=0.75,
            created_at=datetime(2026, 4, 20, 12, 10, tzinfo=UTC),
        )
    )
    await db.commit()

    payload = await channel_stats(db, channel_id=7)

    assert payload == {
        "id": 7,
        "session_count": 1,
        "message_count": 4,
        "total_tokens_in": 30,
        "total_tokens_out": 12,
        "total_cost": pytest.approx(0.75),
    }
