"""Tests for project service."""

import pytest
from sqlalchemy import select

from app.models import Project
from app.services.project import get_project_config, get_user_project_ids


@pytest.mark.asyncio
async def test_get_user_project_ids(db, auth_headers, client):
    from app.models import User

    result = await db.execute(select(User).where(User.username == "admin"))
    admin = result.scalar_one()

    project_ids = await get_user_project_ids(admin.id, db)
    assert len(project_ids) >= 1


@pytest.mark.asyncio
async def test_get_project_config(db):
    result = await db.execute(select(Project).where(Project.name == "demo"))
    project = result.scalar_one_or_none()
    assert project is not None, "Demo project should be seeded"
    assert {"grafana_url", "prometheus_url", "loki_url"} <= set(project.config)

    config = await get_project_config(project.id, db)
    assert not {"grafana_url", "prometheus_url", "loki_url"} & set(config)
    assert config["k8s_context"] == project.config["k8s_context"]
    assert "knowledge" not in config
    assert "repos" not in config and "alert_rules" not in config


@pytest.mark.asyncio
async def test_get_project_config_nonexistent(db):
    config = await get_project_config("nonexistent-id", db)
    assert config == {}
