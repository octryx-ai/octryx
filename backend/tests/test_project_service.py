"""Tests for project service."""

import pytest
from sqlalchemy import select

from app.models import Project
from app.services.project import get_project_config, get_user_project_ids


@pytest.mark.asyncio
async def test_get_user_project_ids(db, auth_headers, client):
    """Admin should have access to demo project."""
    from app.models import User

    result = await db.execute(select(User).where(User.username == "admin"))
    admin = result.scalar_one()

    project_ids = await get_user_project_ids(admin.id, db)
    assert len(project_ids) >= 1


@pytest.mark.asyncio
async def test_get_project_config(db):
    """Project config is the project's own config; the retired KnowledgeMap is no longer merged in.

    A connection never comes from ``Project.config``: the demo seed's ``grafana_url`` /
    ``prometheus_url`` / ``loki_url`` there are dropped, while a non-connection key stays.
    """
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
    """Nonexistent project should return empty dict."""
    config = await get_project_config("nonexistent-id", db)
    assert config == {}
