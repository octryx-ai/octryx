"""A chat's turns run on the server runners: one enrolled, connected runner, and device runs on for every Workspace that
exists when the test starts."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.config import get_settings
from app.models import Project, UserDevice
from app.services.devices.hub import device_hub
from tests.devices.device_support import enable_device_runs, oauth_client
from tests.devices.test_runner_pool import Connected, _enroll


@pytest.fixture
async def chat_pool(client, db, monkeypatch):
    monkeypatch.setattr(get_settings(), "runner_join_secret", "join-secret-for-tests")
    device_hub.clear()
    for project in (await db.execute(select(Project))).scalars().all():
        await enable_device_runs(db, project.name)
    await oauth_client(db)
    await db.commit()  # one SQLite writer: the enrollment request writes next
    enrolled = await _enroll(client, db)
    runner = await db.get(UserDevice, enrolled.json()["device"]["id"])
    await db.commit()  # the read ends its transaction: the test's next request writes (one SQLite writer)
    device_hub._connections[runner.id] = Connected(runner.id)
    yield runner
    device_hub.clear()


__all__ = ["chat_pool"]
