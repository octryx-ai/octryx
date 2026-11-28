"""Git hosts and CI servers sign without a timestamp, so their webhooks always accept untimestamped calls;
the signature or token is still required."""

import pytest
from sqlalchemy import select

from app.models import Project
from app.models.integration.webhook import Webhook


async def _create(client, auth_headers, db, source: str, **more) -> Webhook:
    project = (await db.execute(select(Project))).scalars().first()
    created = await client.post("/api/v1/webhooks", headers=auth_headers, json={
        "project_id": project.id, "name": f"{source} hook", "source_type": source, **more})
    assert created.status_code == 201, created.text
    return await db.get(Webhook, created.json()["id"])


@pytest.mark.asyncio
@pytest.mark.parametrize("source", ["scm_pull_request", "ci_build"])
async def test_a_host_signed_source_accepts_untimestamped_calls_even_when_the_form_says_no(client, auth_headers, db,
                                                                                           source):
    webhook = await _create(client, auth_headers, db, source, accept_untimestamped=False)
    assert webhook.accept_untimestamped is True
    from app.services.admin.connector.admin_webhook_service import update_webhook

    await update_webhook(db, webhook_id=webhook.id, viewer_id=webhook.owner_id, payload={"accept_untimestamped": False, "name": "renamed"})
    await db.refresh(webhook)
    assert webhook.accept_untimestamped is True and webhook.name == "renamed"


@pytest.mark.asyncio
async def test_other_sources_keep_the_admins_choice(client, auth_headers, db):
    webhook = await _create(client, auth_headers, db, "generic")
    assert webhook.accept_untimestamped is False
    from app.services.admin.connector.admin_webhook_service import update_webhook

    await update_webhook(db, webhook_id=webhook.id, viewer_id=webhook.owner_id, payload={"source_type": "scm_pull_request"})
    await db.refresh(webhook)
    assert webhook.accept_untimestamped is True  # now a host-signed source
