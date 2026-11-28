"""Falling back to the next runtime when the primary fails or returns nothing, and building provider client kwargs."""

import pytest

from app.services.control_plane_service import (
    build_provider_client_kwargs,
    build_provider_client_kwargs_async,
)
from tests.control_plane_support import _set_provider_api_key_secret
from tests.model_gateway.conftest import gateway_provider


@pytest.mark.asyncio
async def test_build_provider_client_kwargs_async_resolves_the_virtual_key_only_asynchronously(db):
    provider = gateway_provider(display_name="Encrypted Route", api_key_secret_ref=None, is_global=True)
    db.add(provider)
    await db.flush()
    await _set_provider_api_key_secret(db, provider, "encrypted-gateway-key")
    await db.commit()

    public_kwargs = build_provider_client_kwargs(provider)
    assert public_kwargs["api_key"] is None
    assert "encrypted-gateway-key" not in str(public_kwargs)

    kwargs = await build_provider_client_kwargs_async(db, provider)
    assert kwargs["provider_name"] == "litellm_gateway"
    assert kwargs["api_key"] == "encrypted-gateway-key"
