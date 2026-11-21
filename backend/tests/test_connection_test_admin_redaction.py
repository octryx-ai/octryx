"""The admin device-flow services, the project quality overview and the database connector test keep a closed code and the exception class name, never the exception or provider text."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.services import database_tool_service
from app.services.admin.project import admin_project_quality_overview
from app.services.admin.provider import (
    _admin_control_plane_copilot,
    admin_copilot_service,
)
from app.services.connector_test.failure import CONNECTION_TEST_FAILURE_REASONS
from tests.connection_test_redaction_support import LEAK, LEAK_MARKERS, NARROW_TEXT

# --- admin services (X4) ---------------------------------------------------------------------


async def _raise_leak(*args, **kwargs):
    raise RuntimeError(LEAK)


class _ProviderDb:
    def __init__(self, driver: str):
        self.provider = SimpleNamespace(id="provider-1", name="provider", driver=driver)

    async def execute(self, *args, **kwargs):
        return SimpleNamespace(scalar_one_or_none=lambda: self.provider)

    async def get(self, *args, **kwargs):
        return self.provider

    async def commit(self):
        return None

    async def rollback(self):
        return None


def _assert_clean(value) -> None:
    serialized = json.dumps(value, default=str)
    for marker in LEAK_MARKERS:
        assert marker not in serialized


async def _http_error(call) -> HTTPException:
    with pytest.raises(HTTPException) as raised:
        await call
    assert raised.value.status_code == 502
    assert NARROW_TEXT.fullmatch(raised.value.detail), raised.value.detail
    _assert_clean(raised.value.detail)
    return raised.value


@pytest.mark.asyncio
async def test_copilot_device_flow_errors_keep_only_the_code_and_error_type():
    db = _ProviderDb("copilot_api")
    flow_state: dict = {}
    started = await _http_error(
        admin_copilot_service.start_copilot_device_flow(
            db, provider_id="provider-1", flow_state=flow_state, begin_flow_func=_raise_leak
        )
    )
    assert "error_type=RuntimeError" in started.detail

    async def _refused():
        return {"error": "access_denied", "error_description": LEAK}

    refused = await _http_error(
        admin_copilot_service.start_copilot_device_flow(
            db, provider_id="provider-1", flow_state=flow_state, begin_flow_func=_refused
        )
    )
    assert refused.detail == "access_denied"

    flow_state["f1"] = {"provider_id": "provider-1", "device_code": "d", "interval": 5}
    polled = await _http_error(
        admin_copilot_service.poll_copilot_device_login(
            db,
            provider_id="provider-1",
            flow_id="f1",
            flow_state=flow_state,
            poll_flow_func=_raise_leak,
            provider_secret_scope_func=None,
            set_secret_value_func=None,
            fetch_profile_func=None,
        )
    )
    assert "device_flow_poll_failed" in polled.detail
    _assert_clean(flow_state)

    async def _free_text_code(device_code):
        return {"error": LEAK, "error_description": LEAK}

    failed = await admin_copilot_service.poll_copilot_device_login(
        db,
        provider_id="provider-1",
        flow_id="f1",
        flow_state=flow_state,
        poll_flow_func=_free_text_code,
        provider_secret_scope_func=None,
        set_secret_value_func=None,
        fetch_profile_func=None,
    )
    assert failed == {"status": "failed", "error": "unexpected_error"}
    _assert_clean(flow_state)


@pytest.mark.asyncio
async def test_control_plane_copilot_flow_keeps_only_a_closed_code():
    db = _ProviderDb("copilot_api")
    flow_state = {"f1": {"provider_id": "provider-1", "device_code": "d", "interval": 5}}

    async def _free_text_code(device_code):
        return {"error": LEAK}

    result = await _admin_control_plane_copilot.complete_control_plane_copilot_device(
        db,
        provider_id="provider-1",
        flow_id="f1",
        flow_state=flow_state,
        poll_flow_func=_free_text_code,
        provider_secret_scope_func=None,
        set_secret_value_func=None,
        fetch_profile_func=None,
    )
    assert result["error"] == "unexpected_error"
    _assert_clean(flow_state)


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
