"""Tests for personality endpoints."""

import pytest


@pytest.mark.asyncio
async def test_get_personality_default(client, auth_headers):
    resp = await client.get("/api/v1/personality", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    # Bootstrap should have created admin personality
    assert data["language"] == "en"
    assert data["detail_level"] == "detailed"


@pytest.mark.asyncio
async def test_update_personality(client, auth_headers):
    resp = await client.put(
        "/api/v1/personality",
        json={
            "language": "de",
            "detail_level": "technical",
            "communication_style": "technical",
            "output_format": "full",
            "custom_prompt": "Immer Logs zeigen",
        },
        headers=auth_headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["language"] == "de"
    assert data["custom_prompt"] == "Immer Logs zeigen"


@pytest.mark.asyncio
async def test_update_personality_partial(client, auth_headers):
    resp = await client.put(
        "/api/v1/personality",
        json={"language": "fr"},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["language"] == "fr"
