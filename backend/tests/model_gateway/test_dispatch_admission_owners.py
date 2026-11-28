"""Per-owner seams for propagated model admission."""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.knowledge_graph.llm_runtime import (
    KnowledgeLLMUnavailableError,
    build_generate_fn,
)
from tests.model_gateway.dispatch_admission_owners_support import _project

from .conftest import ALIAS, gateway_runtime, granted_project_config


async def _runtimes() -> list[dict[str, Any]]:
    return [gateway_runtime()]


async def test_knowledge_graph_runtime_refuses_before_building_a_client(db: AsyncSession, monkeypatch):
    project = await _project(db, policy={})
    monkeypatch.setattr(
        "app.services.control_plane_service.resolve_control_plane_runtimes",
        lambda _db, **_kwargs: _runtimes(),
    )

    with pytest.raises(KnowledgeLLMUnavailableError) as denied:
        await build_generate_fn(db, project_ids=project.id)

    assert "No LLM runtime is admitted for this Workspace" in str(denied.value)


async def test_knowledge_graph_runtime_admits_a_granting_workspace(db: AsyncSession, monkeypatch):
    project = await _project(db, policy=granted_project_config(ALIAS)["model_policy"])
    monkeypatch.setattr(
        "app.services.control_plane_service.resolve_control_plane_runtimes",
        lambda _db, **_kwargs: _runtimes(),
    )

    generate = await build_generate_fn(db, project_ids=project.id)

    assert callable(generate)
