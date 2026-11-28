"""A runtime target overrides the sampling catalog (``accepts_temperature``): the admin setting, its stored
value, and the override reaching the provider client."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.agent.runtime.runtime_fallback import _runtime_client_kwargs_for_turn
from app.models import ControlPlaneRuntimeTarget
from app.services.control_plane.selection_policy import build_runtime_selection_payload
from tests.conftest import ADMIN_PASSWORD

TABLE = "control_plane_runtime_targets"
COLUMN = "accepts_temperature"


async def test_the_admin_sets_and_clears_the_override(client, db):
    assert (await client.post("/admin/login", data={"username": "admin", "password": ADMIN_PASSWORD})).status_code == 303
    target = (await db.execute(select(ControlPlaneRuntimeTarget))).scalars().first()
    url = f"/admin/chat/api/panel/runtimes/{target.id}"

    for support, stored in (("rejects", False), ("accepts", True), ("catalog", None)):
        response = await client.put(url, json={"temperature_support": support})
        assert response.status_code == 200 and response.json()["accepts_temperature"] is stored
        await db.refresh(target)
        assert target.accepts_temperature is stored

    assert (await client.put(url, json={"temperature_support": "sometimes"})).status_code == 422
    # Another field's update leaves the override alone.
    await client.put(url, json={"temperature_support": "rejects"})
    await client.put(url, json={"use_case_tags": ["chat"]})
    await db.refresh(target)
    assert target.accepts_temperature is False


@pytest.mark.parametrize("override", [None, True, False])
def test_the_selection_payload_hands_the_override_to_the_provider_client(override):
    target = ControlPlaneRuntimeTarget(id="t", provider_id="p", model_id="claude-sonnet-5", priority=1)
    target.accepts_temperature = override
    payload = build_runtime_selection_payload(
        client_kwargs={"provider_name": "bedrock", "driver": "bedrock_api"},
        provider=None,
        target=target,
        model=None,
        model_id="claude-sonnet-5",
        priority=1,
        use_case_tags=[],
        max_tokens_per_request=None,
        request_timeout_seconds=None,
    )
    assert payload["accepts_temperature"] is override
    assert _runtime_client_kwargs_for_turn(payload)["accepts_temperature"] is override
