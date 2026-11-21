"""The connector descriptor contract: one generic model, connectors only add descriptors.

- the generic modules (table access, resolver, tool router, usage, admin service/view, API) never name a
  connector type: no string constant in their code is a registered connector (docstrings aside);
- every descriptor is consistent with its preset: its secrets are the preset's secret fields, its usable
  field is one of its fields, its binding pattern accepts its example keys;
- every tool a descriptor routes maps back to exactly that descriptor, and no tool is routed twice;
- the public view (what the admin UI renders) flags secrets and never carries a value.
"""

from __future__ import annotations

import ast
import inspect

import pytest

import app.services.admin.project.named_connection_service as admin_service
import app.services.admin.project.named_connection_unit as admin_unit
import app.services.admin.project.named_connection_view as admin_view
import app.services.named_connections.resolver as resolver
import app.services.named_connections.store as store
import app.services.named_connections.tool_routing as tool_routing
import app.services.named_connections.usage as usage
import app.web.routers.panel_named_connections as api
from app.services.named_connections.descriptors import (
    DESCRIPTORS,
    SERVICE_ONLY_CONNECTORS,
    descriptor_for_tool,
    routed_tool_names,
)
from app.services.tool_config.presets import TOOL_CONFIG_PRESETS
from tests.conftest import ADMIN_PASSWORD

GENERIC_MODULES = (resolver, tool_routing, store, usage, admin_service, admin_unit, admin_view, api)


def _code_strings(module) -> set[str]:
    tree = ast.parse(inspect.getsource(module))
    docstrings = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Module | ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            body = getattr(node, "body", [])
            if body and isinstance(body[0], ast.Expr) and isinstance(getattr(body[0], "value", None), ast.Constant):
                docstrings.add(id(body[0].value))
    return {
        node.value.strip().lower()
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docstrings
    }


@pytest.mark.parametrize("module", GENERIC_MODULES, ids=lambda module: module.__name__.rsplit(".", 1)[-1])
def test_generic_modules_never_name_a_connector(module) -> None:
    assert _code_strings(module) & set(DESCRIPTORS) == set()


@pytest.mark.parametrize("connector", sorted(DESCRIPTORS))
def test_a_descriptor_agrees_with_its_preset(connector) -> None:
    descriptor = DESCRIPTORS[connector]
    preset = TOOL_CONFIG_PRESETS[connector]
    assert set(descriptor.secret_fields) <= set(preset.get("secret_fields") or ())
    assert descriptor.usable_field in {item.name for item in descriptor.fields}
    assert len({item.name for item in descriptor.fields}) == len(descriptor.fields)
    for example in descriptor.binding.example.replace(",", " ").split():
        assert descriptor.binding.valid(example), example
    view = descriptor.public()
    assert {item["name"] for item in view["fields"] if item["kind"] == "secret"} == set(descriptor.secret_fields)


@pytest.mark.parametrize("connector", sorted(DESCRIPTORS))
def test_every_routed_tool_maps_back_to_its_one_descriptor(connector) -> None:
    tools = routed_tool_names(connector)
    assert tools or connector in SERVICE_ONLY_CONNECTORS, connector
    for tool_name in tools:
        assert descriptor_for_tool(tool_name) is DESCRIPTORS[connector]
    others = set().union(*(routed_tool_names(other) for other in DESCRIPTORS if other != connector))
    assert tools.isdisjoint(others)


def test_a_tool_of_no_descriptor_is_not_routed() -> None:
    assert descriptor_for_tool("read_file") is None
    assert descriptor_for_tool("") is None


async def test_the_descriptor_list_and_each_list_carry_the_form_the_ui_renders(client, db) -> None:
    assert (await client.post("/admin/login", data={"username": "admin", "password": ADMIN_PASSWORD})).status_code == 303
    listed = (await client.get("/admin/chat/api/panel/named-connection-descriptors")).json()["connectors"]
    assert [item["connector_name"] for item in listed] == list(DESCRIPTORS)
    confluence = next(item for item in listed if item["connector_name"] == "confluence")
    assert confluence["binding"]["plural"] == "Spaces" and confluence["form"] == "atlassian_auth"
    one = (await client.get("/admin/chat/api/panel/connectors/confluence/named-connections")).json()
    assert one["descriptor"] == confluence


async def test_the_policy_summary_names_the_connection_ids_a_policy_can_use(db) -> None:
    from app.models import BuiltInToolConfig
    from app.services.admin.project.named_connection_service import save_named
    from app.services.named_connections.summary import workspace_connection_summary
    from tests.knowledge_evidence_seed_support import seed_workspace

    workspace_id = await seed_workspace(db)
    db.add(BuiltInToolConfig(tool_name="confluence", project_id=workspace_id, is_active=True,
                             config={"confluence_url": "https://wiki.example.test/wiki"}))
    await db.flush()
    saved = await save_named(db, connector="confluence", project_id=workspace_id, actor_id=None, payload={
        "name": "prod", "bound_scopes": ["SALES"], "confluence_url": "https://wiki.example.test/wiki",
        "confluence_auth_mode": "bearer_pat", "confluence_token": "fake-token-1"})

    summary = await workspace_connection_summary(db, workspace_id)

    assert summary == {"confluence": [
        {"id": saved["id"], "name": "prod", "scope": "workspace", "binds": ["SALES"]},
        {"id": "default", "name": "default", "scope": "connector"},
    ]}
    assert "fake-token-1" not in str(summary)
    from app.models import Project
    from app.services.data_classification.workspace_policy_summary import workspace_policy_summary

    policy = await workspace_policy_summary(db, await db.get(Project, workspace_id))
    assert policy["connections"] == summary, "the Workspace policy summary names the ids a Cedar policy can use"
