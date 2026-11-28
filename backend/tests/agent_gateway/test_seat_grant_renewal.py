"""A device renewing its credential keeps its running seat sessions: a renewal never ends a seat turn with
``seat_grant_revoked`` when no login is needed."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.models import AgentPresence, OAuthGrant
from app.models.security.device import UserDevice
from app.services.agent_gateway.contract import SCOPE_MODEL_INVOKE
from app.time_utils import utc_now
from tests.agent_gateway.seat_presence_support import SEAT, _body, _seat_headers, _seat_session
from tests.agent_gateway.seat_upstream_support import anthropic  # noqa: F401 - fixture


async def _renewed(db, workspace_id: str, user_id: str) -> UserDevice:
    row = (await db.execute(select(AgentPresence).where(AgentPresence.project_id == workspace_id))).scalar_one()
    old = await db.get(OAuthGrant, row.seat_grant_id)
    device = UserDevice(owner_user_id=user_id, name="mac", name_key="mac", os="macos", public_key="k")
    db.add(device)
    await db.flush()
    new = OAuthGrant(id=str(uuid.uuid4()), user_id=user_id, client_id=old.client_id, scopes=[SCOPE_MODEL_INVOKE],
                     device_id=device.id)
    db.add(new)
    await db.flush()
    old.device_id, old.revoked_at, device.grant_id = device.id, utc_now(), new.id
    await db.commit()
    return device


@pytest.mark.asyncio
async def test_a_renewed_device_grant_keeps_the_running_seat_session(client, db, anthropic):  # noqa: F811
    workspace_id, user_id, gateway, credential = await _seat_session(client, db)
    await _renewed(db, workspace_id, user_id)

    response = await client.post(SEAT, json=_body(), headers=_seat_headers(gateway, credential))

    assert response.status_code == 200, response.text


@pytest.mark.asyncio
async def test_a_revoked_device_still_ends_the_session(client, db, anthropic):  # noqa: F811
    workspace_id, user_id, gateway, credential = await _seat_session(client, db)
    device = await _renewed(db, workspace_id, user_id)
    device.status = "revoked"
    await db.commit()

    refused = await client.post(SEAT, json=_body(), headers=_seat_headers(gateway, credential))

    assert refused.status_code == 401 and "seat_grant_revoked" in refused.json()["error"]["message"]
    assert anthropic.requests == []
