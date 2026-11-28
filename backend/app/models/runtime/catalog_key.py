"""The stable model catalog key of an ``llm_models`` row: the model id, prefixed with the provider and then numbered
only on a clash. This listener keys every new row."""

from __future__ import annotations

import uuid
from collections.abc import Iterator

from sqlalchemy import event, select

from .llm_provider import LLMModel, LLMProvider

MAX_NUMBERED_KEYS = 50


def catalog_key_candidates(provider_name: str, model_id: str) -> Iterator[str]:
    model = str(model_id or "").strip()
    prefixed = f"{str(provider_name or 'provider').strip() or 'provider'}/{model}"
    yield model
    yield prefixed
    for number in range(2, MAX_NUMBERED_KEYS + 2):
        yield f"{prefixed}-{number}"


@event.listens_for(LLMModel, "before_insert")
def _assign_catalog_key(_mapper, connection, target: LLMModel) -> None:
    if target.catalog_key:
        return
    provider_name = connection.execute(
        select(LLMProvider.name).where(LLMProvider.id == target.provider_id)
    ).scalar_one_or_none()
    for candidate in catalog_key_candidates(provider_name or "", target.model_id):
        taken = connection.execute(select(LLMModel.id).where(LLMModel.catalog_key == candidate)).first()
        if taken is None:
            target.catalog_key = candidate
            return




# A model that enters the platform order without a catalog row (bootstrap, a target writer, a test seed) gets
# one, using the criteria for ordered direct models: enabled, cleared up to ``internal``, tool
# and vision support unknown (as without a row), and the coding capability written once from today's effective value
# (not a weak coding family). An existing row is never changed; clearing a model above ``internal`` is always an
# admin's catalog decision.
ORDERED_MODEL_DEFAULT_CLEARANCE = "internal"


def _register_order_listener() -> None:
    from .control_plane import ControlPlaneRuntimeTarget

    @event.listens_for(ControlPlaneRuntimeTarget, "before_insert")
    def _ensure_catalog_row(_mapper, connection, target: ControlPlaneRuntimeTarget) -> None:
        if not target.provider_id or not target.model_id:
            return
        from ...services.model_family_policy import is_weak_coding_model_family

        table = LLMModel.__table__
        exists = connection.execute(
            select(table.c.id).where(table.c.provider_id == target.provider_id, table.c.model_id == target.model_id)
        ).first()
        if exists is not None:
            return
        provider_name = connection.execute(
            select(LLMProvider.name).where(LLMProvider.id == target.provider_id)
        ).scalar_one_or_none()
        key = next(
            (
                candidate
                for candidate in catalog_key_candidates(provider_name or "", target.model_id)
                if connection.execute(select(table.c.id).where(table.c.catalog_key == candidate)).first() is None
            ),
            None,
        )
        connection.execute(
            table.insert().values(
                id=str(uuid.uuid4()), provider_id=target.provider_id, model_id=target.model_id,
                display_name=target.model_id, is_active=True, supports_streaming=True, catalog_key=key,
                supports_tools=None, supports_vision=None, cleared_up_to=ORDERED_MODEL_DEFAULT_CLEARANCE,
                capabilities_json={"tools": False, "vision": False, "long_context": False,
                                   "coding": not is_weak_coding_model_family(target.model_id)},
            )
        )


_register_order_listener()

__all__ = ["ORDERED_MODEL_DEFAULT_CLEARANCE", "catalog_key_candidates"]
