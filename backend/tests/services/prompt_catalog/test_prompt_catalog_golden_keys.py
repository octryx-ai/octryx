"""Golden test per catalog key: the seed and the seeded database catalog render the pinned reference text
byte for byte (SHA-256 per key in ``tests/prompt_catalog_golden_keys_<area>.py``)."""

from __future__ import annotations

import importlib
import pkgutil
from hashlib import sha256

import pytest

import tests
from app.services.prompt_catalog import resolve_prompt_set
from app.services.prompt_catalog.registry import prompt_key_registry

GOLDEN_MODULE_PREFIX = "prompt_catalog_golden_keys_"


def _pinned() -> dict[str, str]:
    pinned: dict[str, str] = {}
    for module in pkgutil.iter_modules(tests.__path__):
        if module.name.startswith(GOLDEN_MODULE_PREFIX):
            golden = importlib.import_module(f"tests.{module.name}").GOLDEN
            assert not set(golden) & set(pinned), module.name
            pinned.update(golden)
    return pinned


def _samples(key: str) -> dict[str, str]:
    return {name: f"<{name}>" for name in prompt_key_registry()[key].placeholders}


def _digest(text: str) -> str:
    return sha256(text.encode("utf-8")).hexdigest()


def test_every_pinned_key_is_registered_and_its_seed_renders_the_old_text() -> None:
    pinned = _pinned()
    registry = prompt_key_registry()
    assert set(pinned) <= set(registry)
    mismatched = [
        key
        for key, digest in pinned.items()
        if _digest(_render(registry[key].seed, _samples(key))) != digest
    ]
    assert mismatched == []


@pytest.mark.asyncio
async def test_the_seeded_database_catalog_serves_the_same_bytes(db) -> None:
    prompt_set = await resolve_prompt_set(db, workspace_id=None)
    mismatched = [
        key for key, digest in _pinned().items() if _digest(prompt_set.render(key, **_samples(key))) != digest
    ]
    assert mismatched == []


def _render(body: str, variables: dict[str, str]) -> str:
    from app.services.prompt_catalog.contract import render_body

    return render_body("golden", body, variables)
