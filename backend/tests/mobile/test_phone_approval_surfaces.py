"""Confirmation cards on the phone: connector writes and every decidable approval, one call at a time, as in the web."""

from __future__ import annotations

import pytest

from app.services.mobile.session import phone_may_use


@pytest.mark.parametrize(("method", "path", "allowed"), [
    ("POST", "/chat/api/approvals/a1/approve", True),
    ("POST", "/chat/api/approvals/a1/reject", True),
    ("GET", "/chat/api/approvals/a1/approve", False),
    ("POST", "/chat/api/approvals/a1/always", False),
    ("POST", "/chat/api/approvals/a1/approve/x", False),
    ("POST", "/chat/api/sessions/s1/approvals/a1/rerun", False),
    ("POST", "/api/v1/approvals/a1/approve", True),
    ("POST", "/api/v1/approvals/a1/reject", True),
    ("GET", "/api/v1/approvals/decidable", True),
    ("POST", "/api/v1/approvals/a1/always", False),
    ("POST", "/api/v1/approvals/a1/approve/x", False),
    ("POST", "/admin/chat/api/approvals/a1/approve", False),
])
def test_only_listing_approve_and_reject_reach_the_phone_never_always(method, path, allowed):
    assert phone_may_use(method, path) is allowed
