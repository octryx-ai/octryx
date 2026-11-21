"""The server-owned classification source for model-gateway dispatch.

This module reads ``Project.config`` itself instead of accepting a project-config
mapping from its caller, and that is the point of it. The merged turn
``project_config`` that ``prepare_agent_run`` passes around is not a trustworthy
classification source:

- ``services/project/service.get_project_config`` merges the tool configs into it;
- ``agent/core/context/run_context_config.assemble_turn_project_config``
  additionally patches the same dict from session metadata.

Either could let model-reachable state name its own data classification. The
project row is the only place the classification is read from, so caller and
model input cannot choose it — they can only fail to configure it, which denies.

The session raise is read from the session row's metadata and is bounded by the
raise-only rule in :mod:`.classification`.
"""

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
    session_metadata: Mapping[str, Any] | None = None,
) -> WorkspaceDataClassification:
    """Resolve the effective classification for one turn, server-side only.

    A missing project id or a project row that carries no classification yields
    the unresolved value, which denies every gateway dispatch.
    """

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
