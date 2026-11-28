"""The Workspace classification for the coding-agent tool check."""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Mapping
from typing import Any

from ..model_gateway.data_policy.classification import UNRESOLVED_DATA_CLASSIFICATION, WorkspaceDataClassification

logger = logging.getLogger(__name__)

CACHE_SECONDS = 30.0
CACHE_SIZE = 512
_CACHE: dict[str, tuple[float, WorkspaceDataClassification]] = {}


def _key(project_id: str, metadata: Mapping[str, Any] | None) -> str:
    section = metadata.get("data_policy") if isinstance(metadata, Mapping) else None
    return project_id + "|" + json.dumps(section, sort_keys=True, default=str)


async def load_workspace_classification_isolated(
    project_id: str | None, session_metadata: Mapping[str, Any] | None = None
) -> WorkspaceDataClassification:
    from ...db import core as db_core
    from ..model_gateway.data_policy.source import resolve_workspace_data_classification

    normalized = str(project_id or "").strip()
    key = _key(normalized, session_metadata)
    cached = _CACHE.get(key)
    if cached is not None and time.monotonic() - cached[0] < CACHE_SECONDS:
        return cached[1]
    try:
        async with db_core.async_session_factory() as session:
            resolved = await resolve_workspace_data_classification(session, project_id=normalized,
                                                                   session_metadata=session_metadata)
    except Exception:  # noqa: BLE001 - unresolved: classification conditions do not match; nothing is granted
        logger.warning("policy_engine_gateway_classification_failed", exc_info=True)
        return UNRESOLVED_DATA_CLASSIFICATION
    if len(_CACHE) >= CACHE_SIZE:
        _CACHE.clear()
    _CACHE[key] = (time.monotonic(), resolved)
    return resolved


def clear_workspace_facts_cache() -> None:
    _CACHE.clear()


__all__ = ["clear_workspace_facts_cache", "load_workspace_classification_isolated"]
