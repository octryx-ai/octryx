"""DB setup and loading for the control plane: hot path indexes, serialized init_db and bulk provider loads."""

import asyncio

import pytest
from sqlalchemy import inspect

from app.db import async_engine
from app.db.core import init_db
from app.models import LLMProvider
from app.services.control_plane_service import resolve_control_plane_runtimes, upsert_runtime_target
from tests.control_plane_support import _clear_runtime_targets, _set_provider_api_key_secret
from tests.model_gateway.conftest import gateway_provider


@pytest.mark.asyncio
async def test_lightweight_migrations_ensure_hot_path_indexes_exist():
    await init_db()
    async with async_engine.begin() as conn:
        index_names = await conn.run_sync(
            lambda sync_conn: {
                "sessions": {index["name"] for index in inspect(sync_conn).get_indexes("sessions")},
                "task_runs": {index["name"] for index in inspect(sync_conn).get_indexes("task_runs")},
                "task_queue_entries": {index["name"] for index in inspect(sync_conn).get_indexes("task_queue_entries")},
                "cost_allocation_rules": {
                    index["name"] for index in inspect(sync_conn).get_indexes("cost_allocation_rules")
                },
                "monthly_cost_reports": {
                    index["name"] for index in inspect(sync_conn).get_indexes("monthly_cost_reports")
                },
                "approvals": {index["name"] for index in inspect(sync_conn).get_indexes("approvals")},
                "users": {index["name"] for index in inspect(sync_conn).get_indexes("users")},
                "schedulers": {index["name"] for index in inspect(sync_conn).get_indexes("schedulers")},
                "agent_definitions": {index["name"] for index in inspect(sync_conn).get_indexes("agent_definitions")},
            }
        )

    assert "ix_sessions_status" in index_names["sessions"]
    assert "ix_task_runs_status" in index_names["task_runs"]
    assert "ix_task_queue_entries_priority" in index_names["task_queue_entries"]
    assert "ix_cost_allocation_rules_project_id" in index_names["cost_allocation_rules"]
    assert "ix_monthly_cost_reports_period_project_provider" in index_names["monthly_cost_reports"]
    assert "ix_approvals_created_at" in index_names["approvals"]
    assert "ix_users_created_at" in index_names["users"]
    assert "ix_schedulers_created_at" in index_names["schedulers"]
    assert "ix_agent_definitions_updated_at" in index_names["agent_definitions"]


@pytest.mark.asyncio
async def test_init_db_serializes_concurrent_calls(monkeypatch):
    state = {"active": 0, "max_active": 0, "runs": 0}

    class FakeConn:
        async def run_sync(self, fn):
            state["active"] += 1
            state["max_active"] = max(state["max_active"], state["active"])
            state["runs"] += 1
            await asyncio.sleep(0.01)
            state["active"] -= 1

    class FakeBegin:
        async def __aenter__(self):
            return FakeConn()

        async def __aexit__(self, exc_type, exc, tb):
            return False

    class FakeEngine:
        def begin(self):
            return FakeBegin()

    monkeypatch.setattr("app.db.core.async_engine", FakeEngine())

    await asyncio.gather(init_db(), init_db(), init_db())

    assert state["max_active"] == 1
    assert state["runs"] == 6


@pytest.mark.asyncio
async def test_resolve_control_plane_runtimes_bulk_loads_providers_without_per_target_gets(db, monkeypatch):
    await _clear_runtime_targets(db)

    primary_provider = gateway_provider(
        display_name="Primary OpenRouter",
        default_model_id="stepfun/step-3.5-flash:free",
        is_global=True,
        is_active=True,
        api_key_secret_ref=None,
    )
    fallback_provider = gateway_provider(
        display_name="Fallback OpenRouter",
        default_model_id="nvidia/nemotron-3-super-120b-a12b:free",
        is_global=True,
        is_active=True,
        api_key_secret_ref=None,
    )
    db.add(primary_provider)
    db.add(fallback_provider)
    await db.flush()
    await _set_provider_api_key_secret(db, primary_provider, "key-primary")
    await _set_provider_api_key_secret(db, fallback_provider, "key-fallback")

    await upsert_runtime_target(
        db,
        provider=fallback_provider,
        model_id="nvidia/nemotron-3-super-120b-a12b:free",
        make_primary=False,
        is_active=True,
    )
    await upsert_runtime_target(
        db,
        provider=primary_provider,
        model_id="stepfun/step-3.5-flash:free",
        make_primary=True,
        is_active=True,
    )
    await db.commit()

    original_get = db.get
    provider_get_calls: list[str] = []

    async def counting_get(entity, ident, *args, **kwargs):
        if entity is LLMProvider:
            provider_get_calls.append(str(ident))
        return await original_get(entity, ident, *args, **kwargs)

    monkeypatch.setattr(db, "get", counting_get)

    runtimes = await resolve_control_plane_runtimes(db)

    assert len(runtimes) == 2
    assert provider_get_calls == []
