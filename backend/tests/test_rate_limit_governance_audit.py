from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from sqlalchemy import select
from starlette.requests import Request

from app.models import Project, Session, UsageEvent, User
from app.services.auth_rate_limit import (
    AUTH_LOGIN_SCOPE,
    clear_all_auth_rate_limits,
    get_auth_rate_limit_state,
    register_auth_failure,
)
from app.services.auth_rate_limit import service as auth_rate_limit_service
from app.services.worker_pool.helpers import _should_pause_low_priority
from app.services.worker_pool.state import _refresh_rate_limit_usage, get_or_create_worker_rate_limit
from app.time_utils import utc_now


def _make_request(*, client_host: str = "127.0.0.1", forwarded_for: str | None = None) -> Request:
    headers: list[tuple[bytes, bytes]] = []
    if forwarded_for is not None:
        headers.append((b"x-forwarded-for", forwarded_for.encode("latin-1")))
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/api/v1/auth/login",
        "headers": headers,
        "client": (client_host, 12345),
        "query_string": b"",
    }
    return Request(scope)


def test_auth_login_throttling_remains_request_ip_bucketed(monkeypatch) -> None:
    clear_all_auth_rate_limits()
    current_time = [100.0]
    monkeypatch.setattr(auth_rate_limit_service, "monotonic", lambda: current_time[0])

    request_a = _make_request(forwarded_for="10.0.0.1")
    request_b = _make_request(client_host="10.0.0.2")

    state = None
    for _ in range(5):
        state = register_auth_failure(AUTH_LOGIN_SCOPE, request_a)

    assert state is not None
    assert state.limited is True
    assert state.retry_after_header_value == "60"
    assert get_auth_rate_limit_state(AUTH_LOGIN_SCOPE, request_b).limited is False

    clear_all_auth_rate_limits()


@pytest.mark.asyncio
async def test_worker_pool_throttling_remains_project_usage_driven(db) -> None:
    project = (await db.execute(select(Project).where(Project.name == "acme-orders"))).scalar_one()
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()

    session = Session(
        id=str(uuid.uuid4()),
        user_id=admin.id,
        project_id=project.id,
        agent_type="diagnosis",
        status="active",
    )
    db.add(session)
    await db.flush()

    rate_limit = await get_or_create_worker_rate_limit(db, project.id)
    rate_limit.max_requests_per_minute = 10
    rate_limit.max_tokens_per_hour = 1000
    rate_limit.max_cost_per_hour = Decimal("1.00")
    rate_limit.max_cost_per_day = Decimal("2.00")
    rate_limit.on_cost_limit = "pause_low_priority"

    db.add(
        UsageEvent(
            id=str(uuid.uuid4()),
            session_id=session.id,
            user_id=admin.id,
            provider="openai",
            model="gpt-test",
            tokens_in=50,
            tokens_out=75,
            cost=Decimal("1.50"),
            created_at=utc_now(),
        )
    )
    await db.commit()

    await _refresh_rate_limit_usage(db, rate_limit)

    assert rate_limit.current_rpm == 1.0
    assert rate_limit.current_hour_tokens == 125
    assert rate_limit.current_hour_cost == Decimal("1.50")
    assert rate_limit.current_day_cost == Decimal("1.50")
    assert _should_pause_low_priority(rate_limit, 2) is True
    assert _should_pause_low_priority(rate_limit, 8) is False
