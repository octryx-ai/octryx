"""The instance's generated baseline, read from the current sources in the database."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import Project
from ..agent_gateway.policy import resolve_policy_from_config
from ..data_classification.policy_matrix import load_classification_policy
from ..data_classification.workspace_overrides import stored_overrides
from .engine import text_digest
from .translator import WorkspaceSources, instance_baseline


@dataclass(frozen=True, slots=True)
class Baseline:
    text: str
    digest: str
    workspaces: int
    matrix_state: str


async def workspace_sources(db: AsyncSession) -> list[WorkspaceSources]:
    rows = (await db.execute(select(Project.id, Project.config).where(Project.is_active.is_(True)))).all()
    sources: list[WorkspaceSources] = []
    for project_id, config in rows:
        stored = config if isinstance(config, dict) else {}
        model_policy = stored.get("model_policy")
        sources.append(WorkspaceSources(
            str(project_id),
            resolve_policy_from_config(stored).policy,
            model_policy if isinstance(model_policy, dict) else None,
            stored_overrides(stored) or None,
        ))
    return sources


async def load_baseline(db: AsyncSession) -> Baseline:
    matrix = await load_classification_policy(db)
    sources = await workspace_sources(db)
    text = instance_baseline(matrix, sources)
    return Baseline(text, text_digest(text), len(sources), matrix.state)


__all__ = ["Baseline", "load_baseline", "workspace_sources"]
