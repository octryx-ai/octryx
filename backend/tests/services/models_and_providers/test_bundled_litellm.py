"""The bundled LiteLLM: the platform registers it as its one global provider with a virtual key it mints, once, and
never with the master key."""

from __future__ import annotations

import copy

import httpx
import pytest
from sqlalchemy import select

from app.models import LLMProvider
from app.services.model_gateway import bundled_litellm
from app.services.model_gateway.litellm.config import build_gateway_config

URL = "http://127.0.0.1:4000"
MASTER = "sk-bundled-master-0001"
VIRTUAL = "sk-virtual-0001"


@pytest.fixture
def litellm(monkeypatch, tmp_path):
    key_file = tmp_path / "litellm_master_key"
    key_file.write_text(MASTER + "\n")
    monkeypatch.setenv(bundled_litellm.URL_ENV, URL)
    monkeypatch.setenv(bundled_litellm.MASTER_KEY_FILE_ENV, str(key_file))
    calls: list[httpx.Request] = []

    def answer(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json={"key": VIRTUAL})

    original = httpx.AsyncClient

    def client(*args, **kwargs):
        return original(*args, **{**kwargs, "transport": httpx.MockTransport(answer)})

    monkeypatch.setattr(bundled_litellm.httpx, "AsyncClient", client)
    return calls


async def _bundled(db) -> list[LLMProvider]:
    rows = await db.execute(select(LLMProvider).where(LLMProvider.name == bundled_litellm.PROVIDER_NAME))
    return list(rows.scalars())


@pytest.mark.asyncio
async def test_the_bundled_provider_is_registered_once_with_a_minted_virtual_key(db, litellm):
    from app.services.control_plane.provider_auth import PROVIDER_CREDENTIAL
    from app.services.secret import get_secret_value

    provider = await bundled_litellm.register_bundled_provider(db)
    again = await bundled_litellm.register_bundled_provider(db)

    assert again.id == provider.id and len(await _bundled(db)) == 1 and len(litellm) == 1
    request = litellm[0]
    assert (str(request.url), request.headers["authorization"]) == (f"{URL}/key/generate", f"Bearer {MASTER}")
    assert (provider.driver, provider.endpoint_url, provider.is_global) == ("litellm_gateway", f"{URL}/v1", True)
    assert await get_secret_value(db, secret_id=provider.api_key_secret_ref, purpose=PROVIDER_CREDENTIAL) == VIRTUAL
    assert MASTER not in str(provider.config_json)


@pytest.mark.asyncio
async def test_without_the_bundled_service_nothing_is_registered(db, litellm, monkeypatch):
    monkeypatch.delenv(bundled_litellm.URL_ENV)
    assert await bundled_litellm.register_bundled_provider(db) is None
    assert await _bundled(db) == [] and litellm == []


def test_the_bundled_config_is_a_valid_gateway_config_once_an_alias_exists():
    config = copy.deepcopy(bundled_litellm.provider_config(URL))
    config["litellm_gateway"]["aliases"] = {"m1-stub": {
        "model_group": "stub-group", "context_limit": 200000, "data_policy_class": "internal",
        "capabilities": {"tools": True}, "served_model_ids": ["stub-model"],
        "cost": {"source": "catalog_pricing", "input_per_million_usd": 1.0, "output_per_million_usd": 2.0}}}
    gateway = build_gateway_config(endpoint_url=f"{URL}/v1", virtual_key=VIRTUAL, config_json=config)
    assert [alias.alias for alias in gateway.aliases] == ["m1-stub"]
