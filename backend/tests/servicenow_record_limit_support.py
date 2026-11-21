"""Shared helpers for the test_servicenow_record_limit_* modules."""

from __future__ import annotations

import pytest

from tests.servicenow_intake_support import WritingStub, stub

NET_ID = "a" * 32


DESK_ID = "b" * 32


NET = {"display_value": "Network Ops", "value": NET_ID}


DESK = {"display_value": "Service Desk", "value": DESK_ID}


def as_all(row: dict) -> dict:
    """A record as the Table API answers it with ``sysparm_display_value=all``."""
    return {key: value if isinstance(value, dict) else {"display_value": value, "value": value}
            for key, value in row.items()}


# --- chat / Knowledge MCP tools ----------------------------------------------------------------------------------


@pytest.fixture
def sn(monkeypatch):
    instance = WritingStub(incidents=0, changes=0)
    yield from stub(monkeypatch, instance)
