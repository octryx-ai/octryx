"""Shared helpers for the test_servicenow_services_limit_* modules."""

from __future__ import annotations

import pytest

from tests.servicenow_intake_support import WritingStub, incident, stub

DESK = "Shop Support Desk "  # a group name with its trailing space, as ServiceNow stores it


CLOUD = "Platform - Cloud Team"


def row(index: int, group: str | None, service: str | None, state: str = "New") -> dict:
    data = {**incident(index, state), "assignment_group": group, "service": service}
    return {key: value for key, value in data.items() if value is not None}


@pytest.fixture
def sn(monkeypatch):
    instance = WritingStub(incidents=0, changes=0)
    yield from stub(monkeypatch, instance)
