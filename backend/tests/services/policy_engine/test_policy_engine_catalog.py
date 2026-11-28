"""Policy UX: the catalog covers the schema, picker entities, the per-policy view."""

from __future__ import annotations

import json
import re
import uuid

import pytest

from app.models import ConnectorNamedConnection, IdentityGroup, Project, UserGroup
from app.services.policy_engine import catalog
from app.services.policy_engine.custom_policies import custom_digest
from app.services.policy_engine.policy_text import index_statements, join_statements, split_statements
from app.services.policy_engine.schema import ACTIONS, SCHEMA_VERSION, schema_text
from tests.policy_engine_support import BASE, bearer, grant_role, make_user, publish


def _schema_facts() -> dict:
    source = re.sub(r"//[^\n]*", "", schema_text())
    entities = {}
    for name, body in re.findall(r"entity\s+(\w+)(?:\s+in\s+\[[^\]]*\])?\s*(?:\{([^}]*)\})?\s*;", source):
        entities[name] = set(re.findall(r"(\w+)\??\s*:", body or ""))
    types = {name: set(re.findall(r"(\w+)\s*:", body)) for name, body in re.findall(r"type\s+(\w+)\s*=\s*\{([^}]*)\}", source)}
    actions: set[str] = set()
    context: set[str] = set()
    for names, body in re.findall(r"action\s+([\w,\s]+?)\s+appliesTo\s*\{(.*?)\n\};", source, re.S):
        actions |= {item.strip() for item in names.split(",")}
        inline = re.search(r"context:\s*\{([^}]*)\}", body)
        named = re.search(r"context:\s*(\w+)", body)
        context |= set(re.findall(r"(\w+)\s*:", inline.group(1))) if inline else types[named.group(1)]
    return {"entities": entities, "actions": actions, "context": context}


def test_the_catalog_describes_every_action_entity_attribute_and_context_field_of_the_schema():
    facts = _schema_facts()
    payload = catalog.catalog_payload()
    assert payload["schema_version"] == SCHEMA_VERSION
    assert facts["actions"] == set(ACTIONS) == {item["id"] for item in payload["actions"]}
    described = {item["type"]: {attr["name"] for attr in item["attributes"]}
                 for item in payload["principals"] + payload["resources"]}
    assert set(described) == set(facts["entities"])
    for entity, attributes in facts["entities"].items():
        assert described[entity] == attributes, entity
    assert {item["name"] for item in payload["context"]} == facts["context"]
    points = {item["id"] for item in payload["enforcement_points"]}
    for action in payload["actions"]:
        assert action["group"] in payload["action_groups"] and action["point"] in points and action["verb"]
        assert set(action["context"]) <= facts["context"]


def test_blocks_and_templates_only_name_known_actions_and_fields():
    payload = catalog.catalog_payload()
    fields = {block["field"] for block in payload["condition_blocks"]}
    for block in payload["condition_blocks"]:
        assert block["actions"] and set(block["actions"]) <= set(ACTIONS), block["id"]
    for template in payload["templates"]:
        assert set(template["model"]["actions"]) <= set(ACTIONS)
        assert {item["field"] for item in template["placeholders"]} <= fields | {"who.items"}


def test_classification_blocks_follow_the_points_that_carry_the_classification():
    block = catalog.block_info("where.classification_at_least")
    assert set(block["actions"]) == set(catalog.action_ids()), "G7: every point knows the classification"
    assert catalog.block_info("who.role")["actions"] == list(catalog.action_ids())
    action = next(item for item in catalog.catalog_payload()["actions"] if item["id"] == "run_command")
    assert action["carries_user"] is True and action["point_label"] == "Coding-agent tool check"
    assert action["point_when"] == "Checked before a coding agent runs a command or reads or writes a file"


def test_a_catalog_for_another_schema_version_is_refused(tmp_path, monkeypatch):
    stale = json.loads(catalog.CATALOG_PATH.read_text())
    stale["schema_version"] = "1999-01-01.1"
    path = tmp_path / "catalog.json"
    path.write_text(json.dumps(stale))
    monkeypatch.setattr(catalog, "CATALOG_PATH", path)
    catalog._raw.cache_clear()
    try:
        with pytest.raises(catalog.CatalogError):
            catalog.catalog_payload()
    finally:
        monkeypatch.undo()
        catalog._raw.cache_clear()


@pytest.mark.asyncio
async def test_catalog_api_is_for_platform_admins(client, db):
    admin, member = await make_user(db, admin=True), await make_user(db, admin=False)
    assert (await client.get(f"{BASE}/catalog", headers=bearer(member))).status_code == 403
    body = (await client.get(f"{BASE}/catalog", headers=bearer(admin))).json()
    assert [item["id"] for item in body["templates"]][0] == "prod-connection-read-only"
    assert body["connector_families"][0] == "servicenow"


def test_statements_split_outside_strings_and_comments_and_keep_the_trailer():
    text = ('// a; comment\n@id("a") @name("x; y")\nforbid (principal, action, resource) when { resource.line == '
            '"q\\";" };\n\n@id("b")\nforbid (principal, action, resource);\n// tail;\n')
    split = split_statements(text)
    assert split.statements == ('// a; comment\n@id("a") @name("x; y")\nforbid (principal, action, resource) when '
                                '{ resource.line == "q\\";" };', '@id("b")\nforbid (principal, action, resource);')
    assert split.trailer == "// tail;"
    assert join_statements([("b", "B;"), ("a", "A;")], "// t") == "A;\n\nB;\n\n// t\n"
    assert join_statements([]) == ""


def test_index_reads_ids_actions_and_references():
    text = ('@id("w")\n@builder("1")\nforbid (principal in Role::"sre", action == Action::"write_connector", resource)\n'
            'when { context.connections.containsAny(["c-1", "default"]) && context.workspace in [Workspace::"w1"] };')
    (item,) = index_statements(text, every_action=ACTIONS)
    assert item.policy_id == "w" and item.actions == ("write_connector",) and item.annotations["builder"] == "1"
    assert item.references.connections == ("c-1", "default") and item.references.of("Workspace") == ("w1",)
    assert item.references.of("Role") == ("sre",) and item.references.uses_principal


async def _entities(client, admin: str, **params) -> dict:
    response = await client.get(f"{BASE}/catalog/entities", params=params, headers=bearer(admin))
    assert response.status_code == 200, response.text
    return response.json()


@pytest.mark.asyncio
async def test_entities_list_roles_groups_connections_tools_and_aliases(client, db):
    admin, member = await make_user(db, admin=True), await make_user(db, admin=False)
    role = f"role-{uuid.uuid4().hex[:6]}"
    await grant_role(db, member, role)
    group = IdentityGroup(name=f"grp-{uuid.uuid4().hex[:6]}", is_active=True)
    hidden = IdentityGroup(name=f"off-{uuid.uuid4().hex[:6]}", is_active=False)
    db.add_all([group, hidden])
    await db.flush()
    db.add(UserGroup(user_id=member, group_id=group.id))
    project = Project(id=str(uuid.uuid4()), name=f"ws-{uuid.uuid4().hex[:6]}", is_active=True,
                      config={"data_policy": {"classification": "confidential"}})
    db.add(project)
    await db.flush()
    connection = ConnectorNamedConnection(tool_name="servicenow", project_id=project.id, scope_key=project.id,
                                          name="primary", config={}, bound_scopes=["incident"])
    db.add(connection)
    await db.commit()

    body = await _entities(client, admin)
    assert {"name": role, "description": "test role", "member_count": 1} in body["roles"]
    groups = {item["name"]: item for item in body["groups"]}
    assert groups[group.name]["member_count"] == 1 and hidden.name not in groups
    named = next(item for item in body["named_connections"] if item["id"] == connection.id)
    assert named == {"id": connection.id, "name": "primary", "connector": "servicenow", "scope": "workspace",
                     "workspace_id": project.id, "workspace_name": project.name, "bound_scopes": ["incident"]}
    kubectl = next(item for item in body["tools"] if item["name"] == "run_kubectl")
    assert kubectl["connector_family"] == "kubernetes" and kubectl["reads_logs"] is True
    assert {"id": project.id, "name": project.name, "classification": "confidential"} in body["workspaces"]
    assert body["connector_families"][0] == {"id": "servicenow", "label": "ServiceNow"}
    assert isinstance(body["model_aliases"], list)

    narrowed = await _entities(client, admin, type=["roles", "named_connections"], q=role)
    assert set(narrowed) == {"limit", "roles", "named_connections"} and [item["name"] for item in narrowed["roles"]] == [role]
    assert narrowed["named_connections"] == []
    assert len((await _entities(client, admin, type="tools", limit=3))["tools"]) == 3
    refused = await client.get(f"{BASE}/catalog/entities", params={"type": "secrets"}, headers=bearer(admin))
    assert refused.status_code == 422 and refused.json()["detail"]["code"] == "policy_entity_type_unknown"


KEEP = '@id("keep")\n@name("Keep")\nforbid (principal, action == Action::"run_command", resource)\nwhen { resource.program == "rm" };'
EDIT_V1 = '@id("edit")\nforbid (principal, action == Action::"read_path", resource)\nwhen { resource.path like "*.env" };'
EDIT_V2 = '@id("edit")\nforbid (principal, action == Action::"read_path", resource)\nwhen { resource.path like "*.pem" };'
GONE = '@id("gone")\nforbid (principal in Role::"ops", action == Action::"write_connector", resource);'
NEW = ('@id("new")\n@description("Prod read-only")\n@builder("1")\nforbid (principal, action == Action::"write_connector", '
       'resource)\nwhen { context.connections.containsAny(["missing-connection"]) };')


@pytest.mark.asyncio
async def test_the_working_view_lists_policies_with_change_state_history_and_warnings(client, db):
    published = await publish(client, db, "\n\n".join([KEEP, EDIT_V1, GONE]) + "\n")
    author = await make_user(db, admin=True)
    draft = await client.post(f"{BASE}/policy-sets", json={"policies": "\n\n".join([KEEP, EDIT_V2, NEW]) + "\n"},
                              headers=bearer(author))
    assert draft.status_code == 201, draft.text
    body = (await client.get(f"{BASE}/policies", headers=bearer(author))).json()
    assert body["version"]["version"] == draft.json()["version"] and body["published_version"] == published
    items = {item["id"]: item for item in body["items"]}
    assert {key: items[key]["change"] for key in items} == {"keep": "unchanged", "edit": "changed", "new": "new",
                                                            "gone": "removed"}
    assert body["changes"] == {"new": 1, "changed": 1, "removed": 1}
    assert body["edit_target"] == {"version": draft.json()["version"], "digest": draft.json()["digest"],
                                   "creates_draft": False}
    assert items["keep"]["name"] == "Keep" and items["keep"]["source"] == "hand_written"
    assert items["keep"]["last_changed"]["version"] == published
    assert items["edit"]["last_changed"]["version"] == draft.json()["version"]
    assert items["new"]["source"] == "builder" and items["new"]["description"] == "Prod read-only"
    assert items["keep"]["groups"] == ["Coding agent"] and items["keep"]["points"] == ["Coding-agent tool check"]
    assert items["keep"]["scope"] == "All Workspaces"
    assert [warning["code"] for warning in items["new"]["warnings"]] == ["connection_unknown"]
    assert "unknown connection missing-connection" in "".join(seg["text"] for seg in items["new"]["sentence"])
    gone = items["gone"]
    assert gone["warnings"] == [], "every point carries the user since G6"
    assert gone["sentence"][0] == {"text": "Block", "emphasis": "verb"}
    assert "".join(seg["text"] for seg in gone["sentence"]) == "Block members of role ops from changing data."
    assert "generated" not in body

    with_baseline = (await client.get(f"{BASE}/policies", params={"include_generated": "true"},
                                      headers=bearer(author))).json()
    generated = {item["id"]: item for item in with_baseline["generated"]}
    permit = generated["platform:tool-permit"]
    assert permit["source"] == "platform" and permit["effect"] == "permit" and not permit["editable"]
    assert permit["scope"] == "Instance" and permit["sentence"][0]["text"] == "Allow"

    one = (await client.get(f"{BASE}/policy-sets/{published}/policies/edit", headers=bearer(author))).json()
    assert one["change"] == "unchanged" and one["text"] == EDIT_V1
    assert [(entry["version"], entry["change"]) for entry in one["history"]] == [
        (published, "new"), (draft.json()["version"], "changed")]
    missing = await client.get(f"{BASE}/policy-sets/{published}/policies/nope", headers=bearer(author))
    assert missing.status_code == 404 and missing.json()["detail"]["code"] == "policy_not_found"


@pytest.mark.asyncio
async def test_an_empty_instance_has_an_empty_view(client, db):
    admin = await make_user(db, admin=True)
    body = (await client.get(f"{BASE}/policies", headers=bearer(admin))).json()
    assert body["version"] is None and body["items"] == [] and body["changes"] == {"new": 0, "changed": 0,
                                                                                    "removed": 0}
    assert body["edit_target"] == {"version": 0, "digest": custom_digest(""), "creates_draft": True}
