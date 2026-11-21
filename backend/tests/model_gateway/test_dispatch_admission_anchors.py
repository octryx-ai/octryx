"""The Workspace anchor a dispatch owner is allowed to use.

``test_dispatch_admission.py`` proves the boundary and
``test_dispatch_admission_owners.py`` proves each owner's seam. This module pins
the remaining question: *whose* Workspace decides, when the owner's project id can
also come from a model-supplied tool argument.

The knowledge tools resolve their project from ``params["project_id"]``. A model could therefore name a Workspace with a
wider ``model_policy`` and borrow its alias grants. The anchor is server-owned
instead: the turn's own project comes first, the tool's resolved project is
admitted by intersection, and a project outside the actor's own Workspaces is
refused before a client — or a policy row — exists.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Project
from app.services.model_gateway.dispatch_admission import (
    DISPATCH_STATE_DENIED,
    DISPATCH_STATE_NEEDS_CONFIGURATION,
    REASON_CONTEXT_MISSING,
    REASON_CONTEXT_NOT_AUTHORIZED,
)
from app.tools.context import ToolContext
from app.tools.knowledge_impl._knowledge_workspace_scope import (
    CROSS_WORKSPACE_ERROR,
    MISSING_WORKSPACE_ERROR,
    knowledge_workspace_scope,
)

from .conftest import ALIAS, gateway_runtime, granted_project_config

KNOWLEDGE_MODULES = {
    "retrieve": ("app.tools.knowledge_impl._knowledge_retrieve", "KnowledgeRetrieveTool"),
}


async def _project(db: AsyncSession, *, policy: dict | None) -> Project:
    project = Project(
        id=str(uuid.uuid4()),
        name=f"anchor-{uuid.uuid4().hex[:8]}",
        config={
            **({"model_policy": policy} if policy is not None else {}),
            "data_policy": {"classification": "internal"},
        },
        is_active=True,
    )
    db.add(project)
    await db.flush()
    return project


def _context(db: AsyncSession, *, home: Project, also_authorized: Project | None = None) -> ToolContext:
    authorized = [home.id, *([also_authorized.id] if also_authorized else [])]
    return ToolContext(
        user_id="u1",
        project_ids=authorized,
        roles=["operator"],
        session_id="s1",
        # Stamped server-side by ``assemble_turn_project_config`` when the turn was
        # prepared: this, not a tool argument, is the turn's Workspace.
        project_config={"project_id": home.id},
        db=db,
    )


class _ForbiddenDatabase:
    """Proves a refused model argument never becomes a database lookup."""

    async def get(self, *_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("project authorization must happen before db.get")

    async def execute(self, *_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("project authorization must happen before db.execute")


def _preflight_context(*, anchor_id: str | None, authorized_ids: list[str]) -> ToolContext:
    project_config = {"project_id": anchor_id} if anchor_id else {}
    return ToolContext(
        user_id="u1",
        project_ids=authorized_ids,
        roles=["operator"],
        session_id="s1",
        project_config=project_config,
        db=_ForbiddenDatabase(),
    )


# --- the scope itself --------------------------------------------------------


async def test_the_scope_anchors_on_the_turn_project_not_the_model_argument(db: AsyncSession):
    home = await _project(db, policy={"allowed_aliases": [ALIAS]})
    other = await _project(db, policy={"allow_all_admitted_aliases": True})

    scope = knowledge_workspace_scope(_context(db, home=home, also_authorized=other), project_id=other.id)

    # The turn's Workspace is the anchor whose admission is carried; the resolved
    # project only narrows, because the boundary admits by intersection.
    assert scope.anchor_ids == (home.id, other.id)
    assert set(scope.authorized_ids) == {home.id, other.id}
    assert scope.cross_workspace is False


async def test_the_scope_marks_a_project_outside_the_actor_as_cross_workspace(db: AsyncSession):
    home = await _project(db, policy={})
    foreign = await _project(db, policy={"allow_all_admitted_aliases": True})

    scope = knowledge_workspace_scope(_context(db, home=home), project_id=foreign.id)

    assert scope.cross_workspace is True
    denial = scope.denial_result(owner="knowledge_graph_runtime")
    assert denial == {
        "error": CROSS_WORKSPACE_ERROR,
        "status": DISPATCH_STATE_DENIED,
        "dispatch_owner": "knowledge_graph_runtime",
        "admission_reason": REASON_CONTEXT_NOT_AUTHORIZED,
        "dispatched": False,
    }
    # The refusal names the decision, never the project it refused.
    assert foreign.id not in repr(denial)


async def test_the_scope_needs_server_context_before_a_model_can_select_an_authorized_workspace():
    scope = knowledge_workspace_scope(
        _preflight_context(anchor_id=None, authorized_ids=["workspace-a", "workspace-b"]),
        project_id="workspace-b",
    )

    assert scope.allowed is False
    assert scope.anchor_ids == ()
    assert scope.selected_project_id == ""
    assert scope.state == DISPATCH_STATE_NEEDS_CONFIGURATION
    assert scope.reason == REASON_CONTEXT_MISSING


# --- the regression: a model-named foreign Workspace, zero clients -----------


@pytest.mark.parametrize("tool", sorted(KNOWLEDGE_MODULES))
async def test_a_model_supplied_cross_workspace_project_never_reaches_the_database_or_a_client(
    monkeypatch, tool: str
):
    """The foreign Workspace grants the alias; naming it must still dispatch nothing.

    Every path that could produce a request is replaced by a failing stand-in, so
    a green test is the zero-dispatch guarantee rather than a hope: no runtime
    resolution, no generate function, no provider client.
    """

    import importlib

    module_path, tool_name = KNOWLEDGE_MODULES[tool]
    module = importlib.import_module(module_path)
    def _forbidden(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("a cross-Workspace call must resolve nothing and dispatch nothing")

    for attribute in ("resolve_control_plane_runtimes", "build_generate_fn", "get_provider"):
        if hasattr(module, attribute):
            monkeypatch.setattr(module, attribute, _forbidden)
    result = await getattr(module, tool_name)().execute(
        {"project_id": "foreign", "query": "", "force": True, "mode": "global"},
        _preflight_context(anchor_id="home", authorized_ids=["home"]),
    )

    assert result["error"] == CROSS_WORKSPACE_ERROR
    assert result["dispatched"] is False
    assert result["admission_reason"] == REASON_CONTEXT_NOT_AUTHORIZED


@pytest.mark.parametrize("tool", sorted(KNOWLEDGE_MODULES))
async def test_missing_server_anchor_denies_before_the_database_even_for_an_authorized_argument(
    monkeypatch, tool: str
):
    import importlib

    module_path, tool_name = KNOWLEDGE_MODULES[tool]
    module = importlib.import_module(module_path)

    def _forbidden(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("missing turn context must resolve and dispatch nothing")

    for attribute in ("resolve_control_plane_runtimes", "build_generate_fn", "get_provider"):
        if hasattr(module, attribute):
            monkeypatch.setattr(module, attribute, _forbidden)

    result = await getattr(module, tool_name)().execute(
        {"project_id": "workspace-b", "query": "q", "force": True, "mode": "global"},
        _preflight_context(
            anchor_id=None,
            authorized_ids=["workspace-a", "workspace-b"],
        ),
    )

    assert result == {
        "error": MISSING_WORKSPACE_ERROR,
        "status": DISPATCH_STATE_NEEDS_CONFIGURATION,
        "dispatch_owner": "knowledge_graph_runtime",
        "admission_reason": REASON_CONTEXT_MISSING,
        "dispatched": False,
    }


async def test_an_authorized_second_workspace_is_admitted_by_intersection(db: AsyncSession, monkeypatch):
    """Both Workspaces must grant the alias — naming one of them cannot widen it."""

    from app.services.knowledge_graph.llm_runtime import KnowledgeLLMUnavailableError, build_generate_fn

    home = await _project(db, policy=granted_project_config(ALIAS)["model_policy"])
    # Authorized for the actor, but its own policy grants nothing.
    second = await _project(db, policy={})
    monkeypatch.setattr(
        "app.services.control_plane_service.resolve_control_plane_runtimes",
        lambda _db, **_kwargs: _gateway_chain(),
    )
    context = _context(db, home=home, also_authorized=second)
    scope = knowledge_workspace_scope(context, project_id=second.id)

    with pytest.raises(KnowledgeLLMUnavailableError) as denied:
        await build_generate_fn(db, project_ids=list(scope.anchor_ids))

    result = denied.value.to_result()
    assert result["dispatched"] is False
    assert result["admission_evidence"]["project_scope_size"] == 2


async def _gateway_chain() -> list[dict[str, Any]]:
    return [gateway_runtime()]
