"""Shared helpers for the test_connections_admin_api_* modules."""

from __future__ import annotations

import uuid

from app.models import Project
from tests.policy_engine_support import bearer

BASE = "/api/v1/admin"


FAKE = "fake-jira-token-9f3a"


JIRA_URL = "https://octryx.atlassian.example.test"


def _access(**extra) -> dict:
    return {"jira_url": JIRA_URL, "jira_auth_mode": "cloud_api_token", "jira_email": "bot@example.test",
            "jira_token": FAKE, **extra}


async def _workspace(db, name: str | None = None) -> str:
    project = Project(id=str(uuid.uuid4()), name=name or f"ws-{uuid.uuid4().hex[:6]}", is_active=True)
    db.add(project)
    await db.commit()
    return project.id


def _clean(response) -> dict:
    text = response.text
    assert FAKE not in text and "_secret_ref" not in text, "never a secret or a secret ref in a response"
    return response.json()


async def _create(client, admin: str, workspace_id: str, **extra) -> dict:
    body = {"type": "jira", "name": "Jira Cloud (octryx)", "access": _access(), "available_in": "selected",
            "workspaces": [workspace_id], "bound_scopes": ["brd", "ops"], **extra}
    created = await client.post(f"{BASE}/connections", json=body, headers=bearer(admin))
    assert created.status_code == 201, created.text
    return _clean(created)
