"""Inbound webhooks: encrypted, write-only secret; runs as a least-privilege principal."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.api.routes.webhooks import trigger_webhook
from app.models import Project, User
from app.models.integration.webhook import Webhook
from app.services.admin.connector import admin_webhook_service
from app.services.secret import get_secret_value


class _FakeRequest:
    def __init__(self, payload, headers=None):
        self._payload = payload
        self.headers = headers or {}
        self.client = None

    async def body(self):
        import json

        return json.dumps(self._payload).encode()


async def _admin_and_project(db) -> tuple[User, Project]:
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    project = (await db.execute(select(Project).where(Project.name == "acme-orders"))).scalar_one()
    return admin, project


@pytest.mark.asyncio
async def test_admin_created_webhook_secret_is_encrypted_and_never_listed(db):
    admin, project = await _admin_and_project(db)

    created = await admin_webhook_service.create_webhook(
        db, user_id=admin.id, payload={"project_id": project.id, "name": "alerts"}
    )

    raw_secret = created["secret"]
    stored = await db.get(Webhook, created["id"])
    assert stored.secret_ref
    assert await get_secret_value(db, secret_id=stored.secret_ref) == raw_secret
    listed = next(row for row in await admin_webhook_service.list_webhooks(db) if row["id"] == created["id"])
    assert "secret" not in listed
    assert listed["has_secret"] is True
    assert raw_secret not in repr(listed)


# The run-as-service-principal contract is asserted end to end in test_inbound_alert_starts_action.py (V3).


@pytest.mark.asyncio
async def test_webhook_trigger_refuses_a_wrong_secret(db):
    admin, project = await _admin_and_project(db)
    created = await admin_webhook_service.create_webhook(
        db, user_id=admin.id, payload={"project_id": project.id, "name": "guarded"}
    )

    with pytest.raises(Exception) as refused:
        await trigger_webhook(created["id"], _FakeRequest({}, {"X-Webhook-Secret": "wrong"}), db=db)

    assert getattr(refused.value, "status_code", None) == 401
