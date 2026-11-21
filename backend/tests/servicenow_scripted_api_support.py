"""Shared helpers for the test_servicenow_scripted_api_* modules."""

from __future__ import annotations

import pytest

from tests.servicenow_stub_support import StubInstance, stub_instance


@pytest.fixture
def sn(monkeypatch):
    yield from stub_instance(monkeypatch, StubInstance(incidents=95, changes=2))
