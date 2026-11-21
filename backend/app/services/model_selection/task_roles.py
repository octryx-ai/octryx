"""Task models as the role tags the background consumers read.

The summarizer, the episode/memory summaries and the knowledge extraction ask the control-plane chain for a runtime
tagged with their role (``use_case_tags``). Those tags are not typed by an admin on a runtime target: each
runtime carries the roles whose Task model it is (Runtime → Default & fallback → Task models). A task without its
own model uses the platform default (the consumer's untagged path), never a hard-coded model.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import LLMModel
from .task_models import TASK_KNOWLEDGE_GRAPH, TASK_MEMORY, TASK_SUMMARIZE, load_task_models

TASK_ROLE_TAGS = {TASK_SUMMARIZE: "summarize", TASK_MEMORY: "memory", TASK_KNOWLEDGE_GRAPH: "extract"}


async def role_tags_by_ref(db: AsyncSession) -> dict[tuple[str, str], list[str]]:
    """``{(provider id, model id): [role tag]}`` for the models that are a role's Task model."""
    chosen = {task: key for task, key in (await load_task_models(db)).items() if task in TASK_ROLE_TAGS}
    if not chosen:
        return {}
    rows = (
        await db.execute(
            select(LLMModel.catalog_key, LLMModel.provider_id, LLMModel.model_id).where(
                LLMModel.catalog_key.in_(set(chosen.values()))
            )
        )
    ).all()
    refs = {key: (provider_id, model_id) for key, provider_id, model_id in rows}
    tags: dict[tuple[str, str], list[str]] = {}
    for task, key in sorted(chosen.items()):
        if key in refs:
            tags.setdefault(refs[key], []).append(TASK_ROLE_TAGS[task])
    return tags


async def task_model_id(db: AsyncSession, task: str) -> str:
    """The provider model id of a task's own model, or ``""`` (the platform default applies)."""
    key = (await load_task_models(db)).get(task)
    if not key:
        return ""
    return str(
        (await db.execute(select(LLMModel.model_id).where(LLMModel.catalog_key == key))).scalar_one_or_none() or ""
    )


__all__ = ["TASK_ROLE_TAGS", "role_tags_by_ref", "task_model_id"]
