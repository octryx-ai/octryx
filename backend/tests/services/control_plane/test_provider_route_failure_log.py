from __future__ import annotations

import logging
from types import SimpleNamespace

import pytest

from app.services.control_plane import config as control_plane_config


@pytest.mark.asyncio
async def test_a_failing_environment_route_logs_its_traceback_once(monkeypatch, caplog):
    from app.services.model_gateway import bundled_litellm, bundled_routes

    async def provider(_db):
        return SimpleNamespace(default_model_id=None)

    async def failing(_db, _access):
        raise RuntimeError("synthetic: no key for the route")

    monkeypatch.setattr(control_plane_config, "env_model_access", lambda _settings: SimpleNamespace(alias="env-model"))
    monkeypatch.setattr(control_plane_config, "_ROUTE_FAILURES_LOGGED", set())
    monkeypatch.setattr(bundled_litellm, "register_bundled_provider", provider)
    monkeypatch.setattr(bundled_routes, "ensure_route", failing)
    caplog.set_level(logging.DEBUG, logger=control_plane_config.logger.name)
    for _ in range(3):
        assert await control_plane_config.ensure_default_control_plane_provider(
            None, settings=None, infer_provider_runtime_func=None) is None
    errors = [record for record in caplog.records if record.levelno >= logging.ERROR]
    assert len(errors) == 1 and errors[0].exc_info is not None
    assert sum(1 for record in caplog.records if record.levelno == logging.DEBUG) == 2
