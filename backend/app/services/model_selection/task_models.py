"""Task models: the model each background task uses (Runtime → Default & fallback → Task models)."""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import LLMModel, Project
from ..system_config import get_system_config_value, set_system_config_value

TASK_MODELS_KEY = "runtime.task_models"
WORKSPACE_OVERRIDES_KEY = "model_task_overrides"

TASK_SUMMARIZE = "summarize"
TASK_MEMORY = "memory"
TASK_EXTRACT = "extract"
TASK_KNOWLEDGE_GRAPH = "knowledge_graph"
TASK_SECURITY_REVIEW = "security_review"
TASKS: tuple[tuple[str, str], ...] = (
    (TASK_SUMMARIZE, "Conversation summaries"),
    (TASK_MEMORY, "Memory (episode summaries)"),
    (TASK_EXTRACT, "Task extraction from chat"),
    (TASK_KNOWLEDGE_GRAPH, "Knowledge graph extraction"),
    (TASK_SECURITY_REVIEW, "Security analyzer"),
)
TASK_KEYS = frozenset(key for key, _label in TASKS)

ERROR_TASKS_INVALID = "task_models_invalid"
ERROR_TASK_UNKNOWN_MODEL = "task_models_unknown_model"
ERROR_TASK_MODEL_OFF = "task_models_model_not_enabled"
ERROR_TASK_NOT_IN_ORDER = "task_models_model_not_in_order"


class TaskModelsError(ValueError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def decode_task_models(raw: str | None) -> dict[str, str]:
    try:
        value = json.loads(raw) if raw else {}
    except ValueError:
        return {}
    if not isinstance(value, dict):
        return {}
    return {str(task): str(key) for task, key in value.items() if task in TASK_KEYS and isinstance(key, str) and key}


async def load_task_models(db: AsyncSession) -> dict[str, str]:
    return decode_task_models(await get_system_config_value(db, TASK_MODELS_KEY))


def workspace_task_overrides(config: Any) -> dict[str, str]:
    raw = config.get(WORKSPACE_OVERRIDES_KEY) if isinstance(config, dict) else None
    if not isinstance(raw, dict):
        return {}
    return {str(task): str(key) for task, key in raw.items() if task in TASK_KEYS and isinstance(key, str) and key}


async def workspace_override_counts(db: AsyncSession) -> dict[str, int]:
    counts = {key: 0 for key in TASK_KEYS}
    for (config,) in (await db.execute(select(Project.config).where(Project.is_active.is_(True)))).all():
        for task in workspace_task_overrides(config):
            counts[task] += 1
    return counts


async def save_task_models(db: AsyncSession, *, tasks: Any, actor_id: str) -> dict[str, dict[str, str]]:
    if not isinstance(tasks, dict) or set(tasks) - TASK_KEYS:
        raise TaskModelsError(ERROR_TASKS_INVALID)
    chosen = {}
    for task, key in tasks.items():
        if key is None or key == "":
            continue
        if not isinstance(key, str):
            raise TaskModelsError(ERROR_TASKS_INVALID)
        chosen[task] = key.strip()
    if chosen:
        models = {
            model.catalog_key: model
            for model in (
                await db.execute(select(LLMModel).where(LLMModel.catalog_key.in_(set(chosen.values()))))
            ).scalars().all()
        }
        for key in chosen.values():
            if key not in models:
                raise TaskModelsError(ERROR_TASK_UNKNOWN_MODEL)
            if not models[key].is_active:
                raise TaskModelsError(ERROR_TASK_MODEL_OFF)
        # A task model runs through the platform order's runtime of that model (its role tag), so it must be in
        # the order; add it there first.
        from .platform_order import order_targets

        ordered = {(target.provider_id, target.model_id) for target in await order_targets(db)}
        if any((models[key].provider_id, models[key].model_id) not in ordered for key in chosen.values()):
            raise TaskModelsError(ERROR_TASK_NOT_IN_ORDER)
    before = await load_task_models(db)
    await set_system_config_value(
        db, key=TASK_MODELS_KEY, value=json.dumps(chosen, sort_keys=True) if chosen else None,
        description="Model per background task ({task: catalog_key}); absent = the platform default.",
    )
    await db.flush()
    return {"before": before, "after": chosen}


__all__ = [
    "TASKS",
    "TASK_EXTRACT",
    "TASK_KEYS",
    "TASK_KNOWLEDGE_GRAPH",
    "TASK_MEMORY",
    "TASK_MODELS_KEY",
    "TASK_SECURITY_REVIEW",
    "TASK_SUMMARIZE",
    "TaskModelsError",
    "decode_task_models",
    "load_task_models",
    "save_task_models",
    "workspace_override_counts",
    "workspace_task_overrides",
]
