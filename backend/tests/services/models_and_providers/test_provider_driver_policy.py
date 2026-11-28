"""A provider row names one supported driver id; anything else is refused or reported unusable."""

import uuid

import pytest
from sqlalchemy import func, select

from app.models import LLMProvider
from app.services.provider import (
    PROVIDER_DRIVER_UNSUPPORTED_CODE,
    READINESS_NEEDS_CONFIGURATION,
    resolve_provider_readiness,
)
from tests.model_gateway.conftest import BASE_URL, gateway_config, gateway_provider

UNSUPPORTED_DRIVERS = ("openrouter", "openrouter_api", "bedrock_api", "claude_code_cli", "acceptance-driver")
SUBMITTED_PATH = "/opt/acceptance/bin/unsupported-driver"


async def _provider_count(db) -> int:
    return (await db.execute(select(func.count(LLMProvider.id)))).scalar_one()


def _assert_bounded_refusal(response) -> None:
    assert response.status_code == 400, response.text
    detail = response.json()["detail"]
    assert detail["code"] == PROVIDER_DRIVER_UNSUPPORTED_CODE
    # Bounded payload: a fixed code and message plus the static supported catalog.
    assert set(detail) == {"code", "message", "supported_drivers"}
    assert detail["supported_drivers"] == ["litellm_gateway"]
    assert SUBMITTED_PATH not in response.text


@pytest.mark.asyncio
async def test_admin_panel_create_refuses_unsupported_driver_and_writes_no_row(admin_client, db):
    before = await _provider_count(db)

    for driver in UNSUPPORTED_DRIVERS:
        response = await admin_client.post(
            "/admin/chat/api/panel/providers",
            json={"driver": driver, "binary_path": SUBMITTED_PATH, "api_key": "should-never-be-stored"},
        )
        _assert_bounded_refusal(response)

    assert await _provider_count(db) == before


@pytest.mark.asyncio
async def test_admin_panel_create_derives_the_row_from_the_driver_id(admin_client, db):
    response = await admin_client.post(
        "/admin/chat/api/panel/providers",
        json={"driver": "litellm_gateway", "display_name": "Gateway", "endpoint_url": BASE_URL,
              "config_json": gateway_config(), "api_key": "test-key"},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["driver"] == "litellm_gateway"
    assert body["name"] == "litellm_gateway"


@pytest.mark.asyncio
async def test_public_api_create_refuses_unsupported_driver_and_writes_no_row(client, auth_headers, db):
    before = await _provider_count(db)

    for driver in UNSUPPORTED_DRIVERS:
        response = await client.post(
            "/api/v1/providers",
            headers=auth_headers,
            json={"name": "acceptance", "driver": driver, "binary_path": SUBMITTED_PATH},
        )
        _assert_bounded_refusal(response)

    assert await _provider_count(db) == before


@pytest.mark.asyncio
async def test_admin_panel_update_cannot_restate_an_unsupported_driver(admin_client, db):
    provider = gateway_provider(display_name="Supported Row", is_global=True)
    db.add(provider)
    await db.commit()

    refused = await admin_client.put(
        f"/admin/chat/api/panel/providers/{provider.id}",
        json={"driver": "claude_code_cli", "display_name": "Renamed", "binary_path": SUBMITTED_PATH},
    )
    _assert_bounded_refusal(refused)

    await db.refresh(provider)
    assert provider.driver == "litellm_gateway"
    assert provider.display_name == "Supported Row"
    assert provider.binary_path is None

    accepted = await admin_client.put(
        f"/admin/chat/api/panel/providers/{provider.id}",
        json={"display_name": "Still Editable"},
    )
    assert accepted.status_code == 200
    assert accepted.json()["display_name"] == "Still Editable"


@pytest.mark.asyncio
async def test_unsupported_driver_row_is_unusable_listable_and_deletable(admin_client, db):
    row = LLMProvider(
        id=str(uuid.uuid4()),
        name="claude_code_cli",
        provider_family="anthropic",
        driver="claude_code_cli",
        runtime_kind="api",
        display_name="Claude Code",
        auth_mode="profile",
        capabilities_json={"auth_state": "configured"},
        health_status="ok",
        is_global=True,
        is_active=True,
    )
    db.add(row)
    await db.commit()

    # `health_status: ok` would otherwise report ready; the unsupported driver wins.
    readiness = resolve_provider_readiness(row)
    assert readiness["status"] == READINESS_NEEDS_CONFIGURATION
    assert readiness["reason"] == "driver_unsupported"
    assert readiness["runtime_attempt_allowed"] is False

    listed = await admin_client.get("/admin/chat/api/panel/providers")
    assert listed.status_code == 200
    rows = {item["id"]: item for item in listed.json()}
    assert rows[row.id]["readiness"]["reason"] == "driver_unsupported"

    deleted = await admin_client.delete(f"/admin/chat/api/panel/providers/{row.id}")
    assert deleted.status_code == 200
    assert await db.get(LLMProvider, row.id) is None
