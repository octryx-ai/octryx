"""The server-owned classification source for model-gateway dispatch: the project row and the session metadata."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ....models import Project
from .classification import (
    DATA_POLICY_CONFIG_KEY,
    UNRESOLVED_DATA_CLASSIFICATION,
    WorkspaceDataClassification,
    resolve_data_classification,
)


def _data_policy_section(config: Any) -> Any:
    if not isinstance(config, Mapping):
        return None
    return config.get(DATA_POLICY_CONFIG_KEY)


async def resolve_workspace_data_classification(
    db: AsyncSession,
    *,
    project_id: Any,
    session_metadata: Mapping[str, Any] | None = None,  # the session row's own metadata, never a merged config
) -> WorkspaceDataClassification:
    normalized_project_id = str(project_id or "").strip()
    if not normalized_project_id:
        return UNRESOLVED_DATA_CLASSIFICATION
    stored_config = (
        await db.execute(select(Project.config).where(Project.id == normalized_project_id))
    ).scalar_one_or_none()
    return resolve_data_classification(
        project_data_policy=_data_policy_section(stored_config),
        session_data_policy=_data_policy_section(session_metadata),
    )


__all__ = ["resolve_workspace_data_classification"]
