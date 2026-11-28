"""The project quality overview and the database connector test keep a closed code and the exception class name, never the exception or provider text."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from app.services import database_tool_service
from app.services.admin.project import admin_project_quality_overview
from app.services.connector_test.failure import CONNECTION_TEST_FAILURE_REASONS
from tests.support.connection_test_redaction_support import LEAK, LEAK_MARKERS


def _assert_clean(value) -> None:
    serialized = json.dumps(value, default=str)
    for marker in LEAK_MARKERS:
        assert marker not in serialized


def test_project_quality_overview_error_names_only_the_section_and_error_type():
    error = admin_project_quality_overview._overview_error("code_repositories", RuntimeError(LEAK))

    assert error == {
        "section": "code_repositories",
        "error_code": "overview_section_failed",
        "error_type": "RuntimeError",
    }


@pytest.mark.asyncio
async def test_database_connector_test_failure_keeps_only_closed_facts(monkeypatch):
    async def _connector(*args, **kwargs):
        return SimpleNamespace(id="connector-1")

    class _LeakyEngine:
        def connect(self):
            raise ConnectionError(LEAK)

    async def _engine(*args, **kwargs):
        return _LeakyEngine()

    monkeypatch.setattr(database_tool_service, "_load_connector", _connector)
    monkeypatch.setattr(database_tool_service, "resolve_connector_config", _connector)
    monkeypatch.setattr(database_tool_service, "get_connector_engine", _engine)

    result = await database_tool_service.test_database_connector(None, "connector-1")

    assert result["ok"] is False
    assert result["reason"] in CONNECTION_TEST_FAILURE_REASONS
    assert result["error_type"] == "ConnectionError"
    _assert_clean(result)
