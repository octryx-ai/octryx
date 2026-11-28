import uuid

import pytest
from sqlalchemy import select

from app.models import Project
from app.models.integration.webhook import Webhook, WebhookEvent

# The direct prompt-pasting agent run (and its own retry loop) is gone; a call starts the webhook's
# Action through the scheduler, which owns retries. See test_inbound_alert_starts_action.py.


@pytest.mark.asyncio
async def test_list_webhook_events_respects_limit(client, auth_headers, db, auth_user):
    project = (await db.execute(select(Project))).scalars().first()
    assert project is not None

    webhook = Webhook(
        id=str(uuid.uuid4()),
        project_id=project.id,
        owner_id=auth_user.id,
        name="Recent alerts",
        source_type="generic",
        agent_type="diagnosis",
        is_active=True,
    )
    db.add(webhook)
    await db.flush()

    for index in range(3):
        db.add(
            WebhookEvent(
                id=str(uuid.uuid4()),
                webhook_id=webhook.id,
                status=f"received-{index}",
                parsed_message=f"payload-{index}",
            )
        )
    await db.commit()

    response = await client.get(
        f"/api/v1/webhooks/{webhook.id}/events?limit=2",
        headers=auth_headers,
    )

    assert response.status_code == 200
    payload = response.json()
    assert len(payload) == 2


@pytest.mark.asyncio
async def test_list_webhook_events_rejects_limit_above_cap(client, auth_headers, db, auth_user):
    project = (await db.execute(select(Project))).scalars().first()
    assert project is not None

    webhook = Webhook(
        id=str(uuid.uuid4()),
        project_id=project.id,
        owner_id=auth_user.id,
        name="Bounded alerts",
        source_type="generic",
        agent_type="diagnosis",
        is_active=True,
    )
    db.add(webhook)
    await db.commit()

    response = await client.get(
        f"/api/v1/webhooks/{webhook.id}/events?limit=201",
        headers=auth_headers,
    )

    assert response.status_code == 422
