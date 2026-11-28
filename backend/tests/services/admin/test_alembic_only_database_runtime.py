"""Runtime surfaces on a database built by ``alembic upgrade head`` alone, with no ``create_all``; SQLite and, when
configured, PostgreSQL."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
import pytest
from sqlalchemy import event, func, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from app.bootstrap import seed_database
from app.db import get_db
from app.main import app
from app.models import AgentDefinition, Project, User, Webhook, WebhookEvent
from app.services.admin.connector import admin_webhook_service
from app.services.auth import get_current_user
from app.services.secret import get_secret_value
from app.tools.admin_impl._admin_platform import AdminListWebhooksTool
from app.tools.context import ToolContext
from tests.alembic_model_parity_support import DIALECTS, ScratchDatabase, migrated_database, scratch_database


@pytest.fixture(scope="module", params=DIALECTS)
def migrated_template(
    request: pytest.FixtureRequest, tmp_path_factory: pytest.TempPathFactory
) -> Iterator[ScratchDatabase]:
    with migrated_database(request.param, tmp_path_factory.mktemp("alembic-runtime")) as database:
        yield database


@pytest.fixture
def fresh_database(migrated_template: ScratchDatabase, tmp_path: Path) -> Iterator[ScratchDatabase]:
    with scratch_database(migrated_template.dialect, tmp_path, template=migrated_template) as database:
        yield database


def _enable_sqlite_foreign_keys(dbapi_connection: Any, _record: Any) -> None:
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


@dataclass
class RoutedApp:
    engine: AsyncEngine
    factory: async_sessionmaker[AsyncSession]
    principal: dict[str, User] = field(default_factory=dict)


@pytest.fixture
def routed_app(fresh_database: ScratchDatabase, monkeypatch: pytest.MonkeyPatch) -> RoutedApp:
    engine = create_async_engine(fresh_database.url)
    if fresh_database.dialect == "sqlite":
        # The app enforces foreign keys on SQLite (app/db/core.py); so do these checks.
        event.listen(engine.sync_engine, "connect", _enable_sqlite_foreign_keys)
    routed = RoutedApp(engine, async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False))

    async def _database_session() -> AsyncIterator[AsyncSession]:
        async with routed.factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    monkeypatch.setitem(app.dependency_overrides, get_db, _database_session)
    monkeypatch.setitem(app.dependency_overrides, get_current_user, lambda: routed.principal["admin"])
    monkeypatch.setattr(app.state, "async_session_factory", routed.factory)
    return routed


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://parity.test")


async def _count(db: AsyncSession, model: Any, *criteria: Any) -> int:
    return (await db.execute(select(func.count()).select_from(model).where(*criteria))).scalar_one()


async def _seed(routed: RoutedApp) -> Project:
    async with routed.factory() as db:
        await seed_database(db)
        await db.commit()
    async with routed.factory() as db:
        routed.principal["admin"] = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
        return (await db.execute(select(Project).order_by(Project.created_at))).scalars().first()


async def _seed_counts(routed: RoutedApp) -> dict[str, int]:
    try:
        await _seed(routed)
        async with routed.factory() as db:
            return {
                "admins": await _count(db, User, User.username == "admin"),
                "platform_agents": await _count(db, AgentDefinition, AgentDefinition.builtin_key.is_not(None)),
            }
    finally:
        await routed.engine.dispose()


def test_seed_database_runs_on_a_migration_built_schema(routed_app: RoutedApp) -> None:
    counts = asyncio.run(_seed_counts(routed_app))

    assert counts["admins"] == 1
    assert counts["platform_agents"] == 3


async def _wait_for_event(factory: async_sessionmaker[AsyncSession], webhook_id: str) -> WebhookEvent:
    for _ in range(100):
        async with factory() as db:
            found = (await db.execute(select(WebhookEvent).where(
                WebhookEvent.webhook_id == webhook_id, WebhookEvent.outcome != "rejected_signature"))).scalar_one()
            if found.status not in ("received", "processing"):
                return found
        await asyncio.sleep(0.05)
    raise AssertionError("the background webhook run did not finish")


async def _webhook_surfaces(routed: RoutedApp) -> dict[str, Any]:
    try:
        project = await _seed(routed)
        admin = routed.principal["admin"]
        async with _client() as client:
            created = await client.post("/api/v1/webhooks", json={"project_id": project.id, "name": "parity",
                                                                  "accept_untimestamped": True})
            webhook_id = created.json()["id"]
            async with routed.factory() as db:
                stored = await db.get(Webhook, webhook_id)
                raw_secret = await get_secret_value(db, secret_id=stored.secret_ref, purpose="test.read")
            trigger = f"/api/v1/webhooks/{webhook_id}/trigger"
            rejected = await client.post(trigger, json={"text": "parity"}, headers={"X-Webhook-Secret": "wrong"})
            accepted = await client.post(trigger, json={"text": "parity"}, headers={"X-Webhook-Secret": raw_secret})
            processed = await _wait_for_event(routed.factory, webhook_id)

        async with routed.factory() as db:
            admin_created = await admin_webhook_service.create_webhook(
                db, user_id=admin.id, payload={"project_id": project.id, "name": "admin-parity"}
            )
            admin_listed = {item["id"] for item in await admin_webhook_service.list_webhooks(db, viewer_id=admin.id)}
            context = ToolContext(
                user_id=admin.id, project_ids=[project.id], roles=["admin"], session_id="", project_config={}, db=db
            )
            tool_listed = {item["id"] for item in (await AdminListWebhooksTool().execute({}, context))["webhooks"]}
        return {
            "created": created.status_code,
            "secret_ref_resolves": bool(raw_secret),
            "rejected": rejected.status_code,
            "accepted": accepted.status_code,
            "event": (processed.status, processed.outcome),
            "admin_listed": {webhook_id, admin_created["id"]} <= admin_listed,
            "tool_listed": {webhook_id, admin_created["id"]} <= tool_listed,
        }
    finally:
        await routed.engine.dispose()


def test_webhook_api_admin_and_tool_paths_on_a_migration_built_schema(routed_app: RoutedApp) -> None:
    assert asyncio.run(_webhook_surfaces(routed_app)) == {
        "created": 201,
        "secret_ref_resolves": True,
        "rejected": 401,
        "accepted": 202,
        "event": ("skipped", "needs_setup"),
        "admin_listed": True,
        "tool_listed": True,
    }


async def _mash_surfaces(routed: RoutedApp) -> dict[str, Any]:
    try:
        await _seed(routed)
        async with _client() as client:
            token = await client.post(
                "/mash/oauth/token",
                json={"grant_type": "client_credentials", "client_id": "unknown-platform", "client_secret": "x"},
            )
        return {"token": (token.status_code, token.json().get("detail"))}
    finally:
        await routed.engine.dispose()


def test_mash_token_route_on_a_migration_built_schema(routed_app: RoutedApp) -> None:
    assert asyncio.run(_mash_surfaces(routed_app)) == {"token": (401, "invalid_client")}
