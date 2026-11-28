"""Tests for the provider OAuth configuration (``provider_oauth_config``)."""

from __future__ import annotations

import json
import uuid

import pytest
from sqlalchemy import select

from app.models import LLMProvider, ProviderOAuthConfig
from app.models.runtime.provider_oauth_config import (
    oauth_config_columns_from_metadata,
    oauth_config_to_metadata,
    oauth_metadata_from_provider,
)
from app.services.provider.oauth_config_bridge import (
    read_oauth_metadata,
    write_oauth_metadata,
)
from app.web._helpers.panel_serializers import _serialize_provider

# --------------------------------------------------------------------------- #
# Dual-read / dual-write bridge
# --------------------------------------------------------------------------- #


async def _make_provider(db, name: str = "copilot", **kwargs) -> LLMProvider:
    provider = LLMProvider(
        id=str(uuid.uuid4()),
        name=name,
        driver=kwargs.pop("driver", "copilot_api"),
        display_name=name.title(),
        auth_mode="oauth",
        is_global=True,
        is_active=True,
        **kwargs,
    )
    db.add(provider)
    await db.commit()
    return provider


# --------------------------------------------------------------------------- #
# Model helpers
# --------------------------------------------------------------------------- #


def test_columns_from_metadata_splits_typed_and_residual() -> None:
    meta = {
        "oauth_client_id": "cid",
        "google_cloud_project": "proj",
        "login": "a@example.com",
        "has_paid_tier": 1,
        "aws_static_credentials_configured": True,
        "surprise_key": {"nested": "value"},
    }
    columns = oauth_config_columns_from_metadata(meta)
    assert columns["oauth_client_id"] == "cid"
    assert columns["google_cloud_project"] == "proj"
    assert columns["login"] == "a@example.com"
    # bool coercion for the two flag columns
    assert columns["has_paid_tier"] is True
    assert columns["aws_static_credentials_configured"] is True
    # unmapped key preserved in residual, never dropped
    assert columns["residual_json"] == {"surprise_key": {"nested": "value"}}


def test_to_metadata_round_trips_typed_and_residual() -> None:
    config = ProviderOAuthConfig(
        provider_id="p1",
        oauth_client_id="cid",
        login="a@example.com",
        has_paid_tier=True,
        residual_json={"surprise_key": "kept"},
    )
    meta = oauth_config_to_metadata(config)
    assert meta["oauth_client_id"] == "cid"
    assert meta["login"] == "a@example.com"
    assert meta["has_paid_tier"] is True
    assert meta["surprise_key"] == "kept"
    # unset typed columns are omitted (mirrors how flows only set present keys)
    assert "google_cloud_project" not in meta


@pytest.mark.asyncio
async def test_write_oauth_metadata_persists_config_row(db) -> None:
    provider = await _make_provider(db)
    await write_oauth_metadata(
        db,
        provider,
        {"login": "alice-example", "name": "Alice", "source": "github_device_flow", "extra": "x"},
    )
    await db.commit()

    # Normalized config row created with typed + residual values.
    config = (
        await db.execute(select(ProviderOAuthConfig).where(ProviderOAuthConfig.provider_id == provider.id))
    ).scalar_one()
    assert config.login == "alice-example"
    assert config.name == "Alice"
    assert config.source == "github_device_flow"
    assert config.residual_json == {"extra": "x"}

    # The eager relationship is primed so sync readers resolve without a lazy load.
    assert provider.oauth_config is config
    assert oauth_metadata_from_provider(provider)["login"] == "alice-example"


@pytest.mark.asyncio
async def test_read_oauth_metadata_reads_config_row(db) -> None:
    provider = await _make_provider(db)
    await write_oauth_metadata(db, provider, {"login": "from-config"})
    await db.commit()

    meta = await read_oauth_metadata(db, provider)
    assert meta["login"] == "from-config"


@pytest.mark.asyncio
async def test_read_oauth_metadata_empty_when_no_row(db) -> None:
    # Provider with no config row yet resolves to an empty mapping.
    provider = await _make_provider(db)
    meta = await read_oauth_metadata(db, provider)
    assert meta == {}


@pytest.mark.asyncio
async def test_sync_read_sites_resolve_from_config_row(db) -> None:
    # Serializer path (panel_serializers._serialize_provider).
    google = await _make_provider(db, name="google", driver="gemini_api")
    await write_oauth_metadata(
        db,
        google,
        {"oauth_client_id": "cid", "google_cloud_project": "proj", "login": "a@example.com"},
    )
    await db.commit()
    payload = _serialize_provider(google)
    assert payload["auth_login"] == "a@example.com"
    assert payload["google_oauth_client_id"] == "cid"
    assert payload["google_cloud_project"] == "proj"


# --------------------------------------------------------------------------- #
# Serializer contract (must stay byte-identical when read from the config row)
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_serializer_contract_identical_reading_config_row(db) -> None:
    meta = {
        "oauth_client_id": "cid",
        "google_cloud_project": "proj",
        "login": "a@example.com",
        "name": "Ann",
        "host": "https://accounts.google.com",
    }

    # Baseline: a provider whose oauth_config carries the metadata.
    provider = await _make_provider(db, name="google", driver="gemini_api")
    await write_oauth_metadata(db, provider, dict(meta))
    await db.commit()
    from_config = json.dumps(_serialize_provider(provider), sort_keys=True)

    # A transient provider with an equivalent detached config row serializes
    # identically (proves the sync reader is the single source of truth).
    transient = LLMProvider(
        id=provider.id,
        name="google",
        driver="gemini_api",
        display_name="Google",
        auth_mode="oauth",
        is_global=True,
        is_active=True,
        created_at=provider.created_at,
        oauth_config=ProviderOAuthConfig(**oauth_config_columns_from_metadata(meta)),
    )
    from_detached = json.dumps(_serialize_provider(transient), sort_keys=True)

    assert from_config == from_detached
