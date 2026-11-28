from __future__ import annotations

import pytest

from app.services.session import workspace as session_workspace


@pytest.mark.asyncio
async def test_session_workspace_base_dir_uses_env_when_db_value_missing(monkeypatch, tmp_path):
    configured_root = tmp_path / "kubernetes-session-workspaces"

    async def fake_get_system_config_value(_db, _key):
        return None

    monkeypatch.setattr(session_workspace, "get_system_config_value", fake_get_system_config_value)
    monkeypatch.setenv(session_workspace.SESSION_WORKSPACE_BASE_DIR_ENV, str(configured_root))

    resolved = await session_workspace.get_session_workspace_base_dir(object())

    assert resolved == configured_root.resolve()
    assert resolved.exists()


@pytest.mark.asyncio
async def test_session_workspace_db_value_overrides_env(monkeypatch, tmp_path):
    db_root = tmp_path / "db-session-workspaces"
    env_root = tmp_path / "env-session-workspaces"

    async def fake_get_system_config_value(_db, _key):
        return str(db_root)

    monkeypatch.setattr(session_workspace, "get_system_config_value", fake_get_system_config_value)
    monkeypatch.setenv(session_workspace.SESSION_WORKSPACE_BASE_DIR_ENV, str(env_root))

    resolved = await session_workspace.get_session_workspace_base_dir(object())

    assert resolved == db_root.resolve()
    assert resolved.exists()


@pytest.mark.asyncio
async def test_session_workspace_max_age_uses_env_when_db_value_missing(monkeypatch):
    async def fake_get_system_config_value(_db, _key):
        return None

    monkeypatch.setattr(session_workspace, "get_system_config_value", fake_get_system_config_value)
    monkeypatch.setenv(session_workspace.SESSION_WORKSPACE_MAX_AGE_HOURS_ENV, "72")

    assert await session_workspace.get_session_workspace_max_age_hours(object()) == 72
