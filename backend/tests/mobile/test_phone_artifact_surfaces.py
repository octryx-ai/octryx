"""Artifacts on the phone: a Server chat's page/Office preview and diagram picture, read-only."""

from __future__ import annotations

import pytest

from app.services.mobile.session import phone_may_use


@pytest.mark.parametrize(("method", "path", "allowed"), [
    ("GET", "/chat/api/artifact-preview", True),
    ("GET", "/chat/api/artifact-image", True),
    ("POST", "/chat/api/artifact-preview", False),
    ("GET", "/chat/api/artifact", False),
    ("GET", "/chat/api/artifact-inspect", False),
    ("POST", "/chat/api/artifact-actions", False),
    ("GET", "/chat/api/artifact-preview/x", False),
    ("GET", "/chat/api/sessions/s1/workspace", False),
    ("GET", "/chat/api/sessions/s1/workspace/tree", False),
    ("GET", "/api/v1/canvas/sessions/s1", False),
])
def test_only_the_artifact_previews_reach_the_phone(method, path, allowed):
    assert phone_may_use(method, path) is allowed
