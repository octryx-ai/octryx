"""A connector served only by a named connection is active for its Workspace.

- every descriptor connector is active when a usable named connection of the Workspace (or a global one)
  serves it, with no connector config key and no ``enabled_connectors`` entry; one decision function
  (``tools/visibility.connector_activation_decision``) serves chat, discovery, dispatch and platform actions;
- an explicit deactivation still wins; untyped routes and a connection without its URL activate nothing;
- the live case: Workspace ``Test`` holds Bitbucket only as the Workspace named connection
  ``Bitbucket-Cloud-demo-team`` bound to ``demo-team/test`` (its own entry active, empty config): the branch and
  PR tools are visible, ``create_bitbucket_branch`` runs on that connection for ``demo-team/test`` and is
  refused for another repository (the binding rule of the tool router is unchanged).
"""

from __future__ import annotations

import pytest

from app.models import BuiltInToolConfig
from app.services.admin.project.named_connection_service import save_named
from app.services.named_connections.descriptors import DESCRIPTORS
from app.services.named_connections.routes_model import (
    NAMED_CONNECTIONS_KEY,
    ROUTES_UNAVAILABLE,
    NamedConnectionRoutes,
    ResolvedNamedConnection,
)
from app.services.project.service import get_project_config
from app.tools import registry
from app.tools.context import ToolContext
from app.tools.visibility import connector_activation_decision, tool_visibility_decision
from tests.knowledge_evidence_seed_support import seed_workspace


def _routes(*connections: ResolvedNamedConnection) -> dict:
    return {NAMED_CONNECTIONS_KEY: NamedConnectionRoutes(tuple(connections))}


def _named(tool: str, scope: str = "workspace", **config) -> ResolvedNamedConnection:
    return ResolvedNamedConnection(f"nc-{tool}", tool, f"{tool}-named", scope, frozenset({"k"}), config)


@pytest.mark.parametrize("connector", sorted(DESCRIPTORS))
@pytest.mark.parametrize("scope", ["workspace", "global"])
def test_every_connector_is_active_when_a_usable_named_connection_serves_it(connector: str, scope: str) -> None:
    usable_field = DESCRIPTORS[connector].usable_field
    config = _routes(_named(connector, scope, **{usable_field: "https://example.test"}))

    assert connector_activation_decision(connector, config) == (
        True, "named_connection_in_scope", f"named_connection:nc-{connector}",
    )


def test_no_routes_untyped_routes_or_an_unusable_connection_activate_nothing() -> None:
    assert connector_activation_decision("bitbucket", {})[0] is False
    assert connector_activation_decision("bitbucket", {NAMED_CONNECTIONS_KEY: ROUTES_UNAVAILABLE})[0] is False
    assert connector_activation_decision("bitbucket", {NAMED_CONNECTIONS_KEY: {"plain": "dict"}})[0] is False
    assert connector_activation_decision("bitbucket", _routes(_named("bitbucket")))[0] is False
    # Another connector's connection does not activate this one.
    assert connector_activation_decision("bitbucket", _routes(_named("github", github_url="https://x")))[0] is False


def test_an_explicit_deactivation_wins_over_a_named_connection() -> None:
    config = {**_routes(_named("bitbucket", bitbucket_url="https://bitbucket.org")),
              "disabled_connectors": ["bitbucket"]}

    assert connector_activation_decision("bitbucket", config) == (
        False, "explicit_connector_deactivation", "disabled_connectors",
    )


def test_a_composite_connector_is_active_through_a_named_member() -> None:
    config = _routes(_named("github", github_token="fake-token"))

    active, reason, evidence = connector_activation_decision("ci_pipelines", config)
    assert (active, reason) == (True, "member_connector_active")
    assert evidence == "github:named_connection:nc-github"


# --- the live case ---------------------------------------------------------------------------------------


async def _workspace_test(db) -> str:
    workspace_id = await seed_workspace(db, name="Test")
    # Bitbucket switched on for the Workspace, no global entry and no own connection in the entry.
    db.add(BuiltInToolConfig(tool_name="bitbucket", project_id=workspace_id, is_active=True, config={}))
    await db.flush()
    await save_named(db, connector="bitbucket", project_id=workspace_id, actor_id=None, payload={
        "name": "Bitbucket-Cloud-demo-team", "bound_scopes": ["demo-team/test"], "bitbucket_deployment": "cloud",
        "bitbucket_url": "https://bitbucket.org", "bitbucket_username": "owner@example.test",
        "bitbucket_token": "fake-atlassian-token",
    })
    return workspace_id


class _Recorder:
    def __init__(self) -> None:
        self.calls: list[tuple[dict, dict]] = []

    async def __call__(self, params: dict, context: ToolContext) -> dict:
        self.calls.append((params, context.project_config))
        return {"status": "created", "branch": params.get("branch_name")}


async def test_bitbucket_only_via_a_named_connection_is_visible_and_runs_for_its_repository(
    db, monkeypatch,
) -> None:
    workspace_id = await _workspace_test(db)
    config = await get_project_config(workspace_id, db)
    assert "bitbucket_url" not in config

    for tool in ("create_bitbucket_branch", "create_bitbucket_pull_request", "prepare_bitbucket_repository"):
        decision = tool_visibility_decision(tool, config)
        assert decision.visible, (tool, decision)
        assert decision.reason == "named_connection_in_scope"

    recorder = _Recorder()
    monkeypatch.setattr(registry.TOOL_REGISTRY["create_bitbucket_branch"], "execute", recorder)
    context = ToolContext(user_id="u", project_ids=[workspace_id], roles=["admin"], session_id="s",
                          project_config=config, db=db)

    ran = await registry._dispatch_registered_tool(
        "create_bitbucket_branch", {"project_key": "demo-team", "repo_slug": "test", "branch_name": "feature/T-1"},
        context,
    )
    assert ran["status"] == "created"
    _params, used = recorder.calls[0]
    assert used["bitbucket_url"] == "https://bitbucket.org"
    assert used["bitbucket_token"] == "fake-atlassian-token"
    assert [entry["repo_slug"] for entry in used["bitbucket_allowed_repos"]] == ["test"]

    refused = await registry._dispatch_registered_tool(
        "create_bitbucket_branch", {"project_key": "demo-team", "repo_slug": "other", "branch_name": "feature/T-1"},
        context,
    )
    assert refused["code"] == "connection_not_configured_for_scope"
    assert len(recorder.calls) == 1


async def test_the_dispatch_gate_no_longer_refuses_the_named_connection_connector(db) -> None:
    workspace_id = await _workspace_test(db)
    config = await get_project_config(workspace_id, db)

    assert registry.blocked_inactive_connector_tool_result("create_bitbucket_branch", config) is None


async def test_a_disabled_workspace_entry_keeps_the_connector_inactive(db) -> None:
    workspace_id = await _workspace_test(db)
    entry = await db.get(BuiltInToolConfig, (await db.execute(
        BuiltInToolConfig.__table__.select().where(BuiltInToolConfig.project_id == workspace_id)
    )).first().id)
    entry.is_active = False
    await db.flush()

    config = await get_project_config(workspace_id, db)
    assert not tool_visibility_decision("create_bitbucket_branch", config).visible
