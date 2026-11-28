"""One catalog of emitted events; delivery targets only for events that deliver; deliveries named."""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.services.admin.connector.admin_channel_service import SUPPORTED_DELIVERY_EVENTS
from app.services.outbound_webhook.catalog import ALLOWED_OUTBOUND_WEBHOOK_EVENTS, _normalize_event_types


def test_outbound_catalog_lists_only_emitted_events():
    assert "knowledge.updated" not in ALLOWED_OUTBOUND_WEBHOOK_EVENTS, "never emitted"
    assert "worker.monitor.alert" in ALLOWED_OUTBOUND_WEBHOOK_EVENTS, "emitted by the worker monitor"
    assert _normalize_event_types(["worker.monitor.alert"]) == ["worker.monitor.alert"]
    with pytest.raises(HTTPException):
        _normalize_event_types(["knowledge.updated"])


def test_channel_targets_offer_only_events_that_reach_a_workspace_target():
    assert SUPPORTED_DELIVERY_EVENTS == {"approval.requested", "trace.alert.triggered"}
