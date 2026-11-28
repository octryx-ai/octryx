"""The LiteLLM the stack ships: its own database, and the global provider the platform reaches it through with a
virtual key it mints with the master key (which stays in its secret file)."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy import select, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from ...models import LLMProvider
from .litellm.alias_catalog import GATEWAY_CONFIG_KEY

logger = logging.getLogger(__name__)

URL_ENV = "OCTRYX_BUNDLED_LITELLM_URL"
MASTER_KEY_FILE_ENV = "OCTRYX_BUNDLED_LITELLM_MASTER_KEY_FILE"
DATABASE = "litellm"
PROVIDER_NAME = "bundled-litellm"
DRIVER = "litellm_gateway"
_TIMEOUT = 15.0


def bundled_url() -> str:
    return os.environ.get(URL_ENV, "").strip().rstrip("/")


def master_key() -> str:
    path = os.environ.get(MASTER_KEY_FILE_ENV, "").strip()
    return Path(path).read_text(encoding="utf-8").strip() if path else ""


def provider_config(url: str) -> dict[str, Any]:
    host = httpx.URL(url).host
    return {GATEWAY_CONFIG_KEY: {
        "host_allowlist": [host],
        "probe_contract": {"models_path": "/model/info", "response_shape": "openai_model_list",
                           "model_group_field": "model_name"},
        "tls": {"mode": "plaintext_loopback"},
        "proxy": {"mode": "direct"},
        # The stack starts LiteLLM with message logging and every callback off (docker-compose.yml, Helm).
        "content_logging": {
            "mode": "no_content_retention", "prompt_retention": "disabled", "response_retention": "disabled",
            "key_metadata_retention": "disabled", "header_retention": "disabled", "success_callbacks": [],
            "failure_callbacks": [], "attestation_reference": "octryx-bundled-litellm",
            "attested_on": "2026-11-26", "verified_against": "declared_configuration"},
        "aliases": {},
    }}


async def _virtual_key(url: str, key: str) -> str:
    async with httpx.AsyncClient(timeout=_TIMEOUT, trust_env=False) as client:
        response = await client.post(f"{url}/key/generate", headers={"Authorization": f"Bearer {key}"},
                                     json={"metadata": {"owner": "octryx-platform"}})
    response.raise_for_status()
    return str(response.json()["key"])


async def register_bundled_provider(db: AsyncSession) -> LLMProvider | None:
    from ...schemas.operations.provider import ProviderCreate
    from ..provider.service import create_provider_response

    url, key = bundled_url(), master_key()
    if not url or not key:
        return None
    existing = (await db.execute(select(LLMProvider).where(LLMProvider.name == PROVIDER_NAME))).scalar_one_or_none()
    if existing is not None:
        return existing
    body = ProviderCreate(driver=DRIVER, name=PROVIDER_NAME, display_name="Bundled LiteLLM",
                          endpoint_url=f"{url}/v1", auth_mode="api_key", api_key=await _virtual_key(url, key),
                          config_json=provider_config(url), is_global=True)
    await create_provider_response(db, body, None)
    return (await db.execute(select(LLMProvider).where(LLMProvider.name == PROVIDER_NAME))).scalar_one()


async def ensure_database(database_url: str) -> bool:
    url = make_url(database_url)
    engine = create_async_engine(url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    try:
        async with engine.connect() as connection:
            found = await connection.scalar(text("SELECT 1 FROM pg_database WHERE datname = :name"),
                                            {"name": DATABASE})
            if found:
                return False
            await connection.execute(text(f'CREATE DATABASE "{DATABASE}"'))
            return True
    finally:
        await engine.dispose()


if __name__ == "__main__":
    import asyncio

    created = asyncio.run(ensure_database(os.environ["DATABASE_URL"]))
    print(f"litellm database {'created' if created else 'present'}")


__all__ = ["DATABASE", "PROVIDER_NAME", "URL_ENV", "bundled_url", "ensure_database", "master_key", "provider_config",
           "register_bundled_provider"]
