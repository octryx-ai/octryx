"""Roles on the phone: "My role" and, for Workspace admins, the Workspace's assignments, read-only. Every
write of the roles API (assignments, the switch, roles, functions, SSO mapping) and the admin preview of another
person's permission stay off the phone; the routes keep their own access checks.
"""

from __future__ import annotations

import pytest

from app.services.mobile.session import phone_may_use


@pytest.mark.parametrize(("method", "path", "allowed"), [
    ("GET", "/api/v1/work-roles/workspaces/w1/me", True),
    ("GET", "/api/v1/work-roles/workspaces/w1", True),
    ("POST", "/api/v1/work-roles/workspaces/w1/me", False),
    ("PUT", "/api/v1/work-roles/workspaces/w1/settings", False),
    ("GET", "/api/v1/work-roles/workspaces/w1/settings", False),
    ("POST", "/api/v1/work-roles/workspaces/w1/assignments", False),
    ("PATCH", "/api/v1/work-roles/workspaces/w1/assignments/a1", False),
    ("GET", "/api/v1/work-roles/workspaces/w1/effective", False),
    ("GET", "/api/v1/work-roles/workspaces/w1/me/x", False),
    ("GET", "/api/v1/work-roles/roles", False),
    ("PUT", "/api/v1/work-roles/roles/r1/trusted", False),
])
def test_only_reading_the_roles_of_a_workspace_reaches_the_phone(method, path, allowed):
    assert phone_may_use(method, path) is allowed
