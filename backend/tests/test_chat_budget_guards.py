"""Budget and session cost guards: warning alerts, default blocks and blocking a chat send before the provider call."""

import asyncio
import uuid
from decimal import Decimal

import pytest
from sqlalchemy import select

import app.agent.engine as engine_module
from app.exceptions.tool import BudgetLimitExceededError
from app.models import BudgetAlert, BudgetPolicy, LLMModel, LLMProvider, Session, UsageEvent, User
from app.services.budget import enforce_budget_limits
from tests.conftest import ADMIN_PASSWORD


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_budget_guard_emits_warning_alert_before_threshold_block(db):
    admin_user = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    policy = BudgetPolicy(
        id=str(uuid.uuid4()),
        name="Warning threshold",
        user_id=admin_user.id,
        daily_token_limit=100,
        warn_at_percent=80,
        block_at_percent=100,
        is_active=True,
    )
    db.add(policy)
    await db.commit()

    await enforce_budget_limits(
        db,
        session_id=str(uuid.uuid4()),
        user_id=admin_user.id,
        project_id=None,
        runtimes=[],
        messages=[{"role": "user", "content": "a" * 320}],
        max_completion_tokens=0,
        approx_chars_per_token=4,
    )

    alerts = (
        (
            await db.execute(
                select(BudgetAlert).where(
                    BudgetAlert.policy_id == policy.id,
                    BudgetAlert.metric_name == "tokens",
                    BudgetAlert.threshold_level == "warning",
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(alerts) == 1
    assert alerts[0].percent_used >= 80


@pytest.mark.asyncio
async def test_default_session_cost_guard_blocks_without_budget_policy(db, monkeypatch):
    admin_user = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    session = Session(id=str(uuid.uuid4()), user_id=admin_user.id, status="active")
    provider = LLMProvider(id=str(uuid.uuid4()), name="bedrock", driver="bedrock_api", display_name="Bedrock", is_active=True)
    model = LLMModel(
        id=str(uuid.uuid4()),
        provider_id=provider.id,
        model_id="expensive-model",
        pricing_input=2.0,
        pricing_output=2.0,
        is_active=True,
    )
    db.add_all(
        [
            session,
            provider,
            model,
            UsageEvent(
                id=str(uuid.uuid4()),
                session_id=session.id,
                user_id=admin_user.id,
                provider="bedrock",
                model="expensive-model",
                tokens_in=1,
                tokens_out=0,
                cost=Decimal("0.000002"),
            ),
        ]
    )
    await db.commit()
    monkeypatch.setenv("OCTRYX_AGENT_SESSION_COST_LIMIT_USD", "0.000003")

    with pytest.raises(BudgetLimitExceededError) as exc:
        await enforce_budget_limits(
            db,
            session_id=session.id,
            user_id=admin_user.id,
            project_id=None,
            runtimes=[{"provider_name": "bedrock", "model": "expensive-model"}],
            messages=[{"role": "user", "content": "x"}],
            max_completion_tokens=0,
            approx_chars_per_token=4,
        )

    assert exc.value.policy_name == "Default agent session cost guard"


@pytest.mark.asyncio
@pytest.mark.committed_db
async def test_chat_send_budget_guard_blocks_before_provider_call(client, db, monkeypatch):
    login_resp = await client.post("/admin/login", data={"username": "admin", "password": ADMIN_PASSWORD})
    assert login_resp.status_code == 303

    admin_user = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    prior_session = Session(
        id=str(uuid.uuid4()),
        user_id=admin_user.id,
        project_id=None,
        agent_type="chat",
        status="active",
        metadata_={},
    )
    db.add(prior_session)
    await db.flush()
    db.add(
        UsageEvent(
            id=str(uuid.uuid4()),
            session_id=prior_session.id,
            user_id=admin_user.id,
            provider="copilot",
            model="claude-haiku-4.5",
            tokens_in=5,
            tokens_out=5,
            cost=0,
        )
    )
    db.add(
        BudgetPolicy(
            id=str(uuid.uuid4()),
            name="Daily request cap",
            user_id=admin_user.id,
            daily_request_limit=1,
            warn_at_percent=80,
            block_at_percent=100,
            is_active=True,
        )
    )
    await db.commit()

    async def fake_resolve_control_plane_runtimes(_db, runtime_target_id=None):
        return [{"provider_name": "copilot", "model": "claude-haiku-4.5"}]

    async def fake_chat_with_runtime_fallback(**kwargs):
        raise AssertionError("runtime fallback should not be called when budget is exhausted")

    monkeypatch.setattr(engine_module, "resolve_control_plane_runtimes", fake_resolve_control_plane_runtimes)
    monkeypatch.setattr(engine_module, "_chat_with_runtime_fallback", fake_chat_with_runtime_fallback)

    send_resp = await client.post(
        "/admin/chat/api/send",
        json={"prompt": "Explain the current state."},
    )
    assert send_resp.status_code == 200
    session_id = send_resp.json()["selectedSession"]["id"]

    final_payload = send_resp.json()
    for _ in range(40):
        await asyncio.sleep(0.05)
        bootstrap_resp = await client.get(f"/admin/chat/api/bootstrap?session_id={session_id}")
        assert bootstrap_resp.status_code == 200
        final_payload = bootstrap_resp.json()
        if not final_payload["selectedSessionIsRunning"]:
            break

    assistant_messages = [item for item in final_payload["selectedMessages"] if item["role"] == "assistant"]
    assert assistant_messages
    assert "Budget policy 'Daily request cap' exceeded" in assistant_messages[-1]["content"]

    alerts = (
        (
            await db.execute(
                select(BudgetAlert).where(
                    BudgetAlert.metric_name == "requests",
                    BudgetAlert.threshold_level == "block",
                )
            )
        )
        .scalars()
        .all()
    )
    assert alerts
