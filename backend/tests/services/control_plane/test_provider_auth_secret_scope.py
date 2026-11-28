from __future__ import annotations

import uuid

from app.models import LLMProvider
from app.services.control_plane.provider_auth import (
    CONTROL_PLANE_PROVIDER_TOOL_PREFIX,
    DEFAULT_PROVIDER_SECRET_KEY,
    provider_secret_scope,
    provider_secret_tool_name,
)


def test_provider_secret_tool_name_uses_provider_prefix_and_id():
    provider = LLMProvider(id=str(uuid.uuid4()), name="openrouter", driver="openrouter_api")

    assert provider_secret_tool_name(provider) == f"{CONTROL_PLANE_PROVIDER_TOOL_PREFIX}:{provider.id}"


def test_provider_secret_scope_uses_default_scope_for_missing_provider():
    assert provider_secret_tool_name(None) == f"{CONTROL_PLANE_PROVIDER_TOOL_PREFIX}:{DEFAULT_PROVIDER_SECRET_KEY}"
    assert provider_secret_scope(None, "refresh_token") == (
        f"{CONTROL_PLANE_PROVIDER_TOOL_PREFIX}:{DEFAULT_PROVIDER_SECRET_KEY}",
        "refresh_token",
    )
