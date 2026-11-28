"""Which stored secrets a deleted global connector config leaves behind, and their release."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ...secret import get_secret_entry
from ...secret.release import ExcludedHolder, SecretReleaseOutcome, config_secret_refs, release_unreferenced_secrets
from ...tool_config import TOOL_CONFIG_PRESETS


async def connector_secret_candidates(db: AsyncSession, *, tool_name: str, config_entry: Any | None) -> set[str]:
    candidates = config_secret_refs(dict(config_entry.config or {}) if config_entry else {})
    for field_name in TOOL_CONFIG_PRESETS.get(tool_name, {}).get("secret_fields", []):
        entry = await get_secret_entry(db, tool_name=tool_name, field_name=field_name, project_id=None)
        if entry is not None:
            candidates.add(entry.id)
    return candidates


async def release_connector_secrets(
    db: AsyncSession,
    candidate_secret_ids: set[str],
    *,
    config_entry: Any | None,
) -> SecretReleaseOutcome:
    excluded = ExcludedHolder(table="built_in_tool_configs", row_id=config_entry.id) if config_entry else None
    return await release_unreferenced_secrets(db, candidate_secret_ids, excluded=excluded)
