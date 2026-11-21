"""More › Seat on the phone: the Workspace's seat switches are read from the phone; changing them, and
every other agent-gateway admin route, stays in the web."""

from __future__ import annotations

import pytest

from app.services.mobile.session import phone_may_use


@pytest.mark.parametrize(("method", "path", "allowed"), [
    ("GET", "/api/v1/workspaces/w1/agent-gateway/seat-mode", True),
    ("PUT", "/api/v1/workspaces/w1/agent-gateway/seat-mode", False),
    ("POST", "/api/v1/workspaces/w1/agent-gateway/seat-mode", False),
    ("GET", "/api/v1/workspaces/w1/agent-gateway/seat-mode/x", False),
    ("GET", "/api/v1/workspaces/w1/x/agent-gateway/seat-mode", False),
    ("GET", "/api/v1/workspaces/w1/agent-gateway/policy", False),
])
def test_only_reading_the_seat_switches_reaches_the_phone(method, path, allowed):
    assert phone_may_use(method, path) is allowed
