"""Policy UX: the builder round trip (goldens) and policy-level saves with If-Match."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.models import ConnectorNamedConnection
from app.services.policy_engine import catalog
from app.services.policy_engine.builder import render
from app.services.policy_engine.builder_model import model_from_json, used_blocks
from app.services.policy_engine.builder_parse import parse
from app.services.policy_engine.custom_policies import check_custom_policies, custom_digest
from tests.policy_engine_support import BASE, bearer, make_user, publish

GOLDENS = json.loads((Path(__file__).parents[2] / "fixtures" / "policy_builder_goldens.json").read_text(encoding="utf-8"))
FILL = {"where.connections": ["c-1"], "what.models": ["approved-model"], "who.items": ["sre"],
        "conditions.unless_option_values": ["--context=<non-prod context>"], "outcome.reroute_to": "approved-model",
        "content.detectors": ["custom.example_detector"]}
CUSTOM = {"custom.example_detector": "confidential_identifier"}


def _model(raw):
    model, issues = model_from_json(raw)
    assert model is not None, issues
    return model


# --- G5: deterministic render, strict parse ---------------------------------------------------------------------


@pytest.mark.parametrize("name", sorted(GOLDENS))
def test_goldens_render_exactly_validate_and_round_trip(name):
    golden = GOLDENS[name]
    model = _model(golden["model"])
    text = render(model)
    assert text == golden["cedar"]
    assert check_custom_policies(text).ids == (golden["model"]["id"],)
    assert parse(text) == model, "parse(render(m)) == m"
    assert render(parse(golden["cedar"])) == golden["cedar"], "render(parse(t)) == t"


def test_the_goldens_cover_every_condition_block_of_the_catalog():
    covered = {block for golden in GOLDENS.values() for _, block in used_blocks(_model(golden["model"]))}
    assert set(catalog.block_ids()) - covered == {"who.everyone"}


@pytest.mark.parametrize("template", [item["id"] for item in catalog.templates()])
def test_every_template_needs_its_placeholders_then_renders_valid_cedar(template):
    info = catalog.template_info(template)
    raw = {"id": f"tpl.{template}", "template": template, **json.loads(json.dumps(info["model"]))}
    if info["placeholders"]:
        _, issues = model_from_json(raw, CUSTOM)
        assert {issue["path"] for issue in issues if issue["code"] == "builder_template_placeholder_missing"} == {
            item["field"] for item in info["placeholders"]}
    for placeholder in info["placeholders"]:
        section, name = placeholder["field"].split(".")
        raw.setdefault(section, {})[name] = FILL[placeholder["field"]]
    model, issues = model_from_json(raw, CUSTOM)
    assert model is not None, issues
    text = render(model)
    check_custom_policies(text)
    assert parse(text) == model and f'@template("{template}")' in text


@pytest.mark.parametrize("text", [
    # annotation order differs from the renderer
    '@id("x")\n@builder("1")\n@name("N")\nforbid (principal, action == Action::"use_seat", resource);',
    # an annotation the builder does not write
    '@id("x")\n@owner("me")\n@builder("1")\nforbid (principal, action == Action::"use_seat", resource);',
    # reformatted by hand
    '@id("x")\n@builder("1")\nforbid (principal, action == Action::"use_seat", resource) ;',
    # OR across steps
    '@id("x")\n@builder("1")\nforbid (principal, action == Action::"run_command", resource)\n'
    'when { ["kubectl"].contains(resource.program) || !resource.parseable };',
    # a block twice
    '@id("x")\n@builder("1")\nforbid (principal, action == Action::"run_command", resource)\n'
    'when { resource.prefixes.containsAny(["a"]) && resource.prefixes.containsAny(["b"]) };',
    # principal == instead of in
    '@id("x")\n@builder("1")\nforbid (principal == User::"u", action == Action::"use_seat", resource);',
    # actions out of catalog order
    '@id("x")\n@builder("1")\nforbid (principal, action in [Action::"write_path", Action::"read_path"], resource);',
    # no builder annotation at all
    '@id("x")\nforbid (principal, action == Action::"use_seat", resource);',
    # a block that does not apply to the action
    '@id("x")\n@builder("1")\nforbid (principal, action == Action::"run_command", resource)\n'
    'when { context.connections.containsAny(["c"]) };',
    # mixed model modes
    '@id("x")\n@builder("1")\nforbid (principal, action == Action::"call_model", resource)\n'
    'when { ["a"].contains(resource.alias) }\nunless { ["b"].contains(resource.alias) };',
])
def test_parse_refuses_anything_the_renderer_does_not_produce(text):
    assert parse(text) is None


@pytest.mark.parametrize(("raw", "path", "code"), [
    ({"id": "x", "actions": []}, "actions", "builder_action_required"),
    ({"id": "platform:x", "actions": ["use_seat"]}, "id", "builder_policy_id_invalid"),
    ({"id": "x", "actions": ["use_seat"], "colour": "red"}, ".colour", "builder_field_unknown"),
    ({"id": "x", "actions": ["use_seat"], "who": {"mode": "roles"}}, "who.items", "builder_who_items_required"),
    ({"id": "x", "actions": ["run_command"], "where": {"connections": ["c"]}},
     "where.connections", "builder_block_not_applicable"),
    ({"id": "x", "actions": ["call_model", "use_seat"], "what": {"models": ["a"]}}, "what.models",
     "builder_block_not_applicable"),
    ({"id": "x", "actions": ["read_path"], "what": {"paths": ["*.en?"]}}, "what.paths[0]", "builder_value_invalid"),
    ({"id": "x", "actions": ["use_seat"], "conditions": {"seat_mode": "sometimes"}}, "conditions.seat_mode",
     "builder_value_invalid"),
    ({"id": "x", "actions": ["call_tool"], "what": {"tools": [" padded "]}}, "what.tools[0]", "builder_value_invalid"),
])
def test_the_model_reader_names_every_problem(raw, path, code):
    model, issues = model_from_json(raw)
    assert model is None and {"path": path, "code": code} in [{"path": i["path"], "code": i["code"]} for i in issues]


def test_the_model_is_normalized_so_equal_policies_have_equal_models():
    model = _model({"id": "x", "actions": ["write_path", "read_path"], "what": {"paths": ["a", "a", "b"],
                                                                                 "model_mode": "only"}})
    assert model.actions == ("read_path", "write_path") and model.what.paths == ("a", "b")
    assert model.what.model_mode == "except", "an unused model mode is the default"


# --- render preview ---------------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_render_preview_returns_cedar_sentence_scope_and_warnings(client, db):
    admin = await make_user(db, admin=True)
    connection = ConnectorNamedConnection(tool_name="servicenow", project_id=None, scope_key="global",
                                          name="primary", config={}, bound_scopes=[])
    db.add(connection)
    await db.commit()
    model = {"id": "prod-read-only", "name": "Prod read-only", "actions": ["write_connector"],
             "who": {"mode": "roles", "items": ["sre"], "except_admins": True},
             "what": {"families": ["servicenow"]}, "where": {"connections": [connection.id, "gone-id"]}}
    body = (await client.post(f"{BASE}/policy-builder/render", json={"model": model}, headers=bearer(admin))).json()
    assert body["valid"] is True and body["issues"] == []
    assert body["text"] == render(_model(model))
    sentence = "".join(segment["text"] for segment in body["sentence"])
    assert sentence == ("Block members of role sre from changing data through ServiceNow on connection primary or "
                        "unknown connection gone-id in all Workspaces, except for platform admins.")
    assert body["sentence"][0] == {"text": "Block", "emphasis": "verb"}
    assert body["scope"] == "Connection primary or unknown connection gone-id"
    assert [warning["code"] for warning in body["warnings"]] == ["connection_unknown"], "G6: the user is carried"
    refused = (await client.post(f"{BASE}/policy-builder/render", json={"model": {"id": "x", "actions": []}},
                                 headers=bearer(admin))).json()
    assert refused["valid"] is False and refused["issues"][0]["code"] == "builder_action_required"
    member = await make_user(db, admin=False)
    assert (await client.post(f"{BASE}/policy-builder/render", json={"model": model},
                              headers=bearer(member))).status_code == 403


# --- G9: policy-level saves -------------------------------------------------------------------------------------

SEAT = '@id("b-seat")\nforbid (principal, action == Action::"use_seat", resource);'
KEEP = '@id("a-keep")\nforbid (principal, action == Action::"run_command", resource)\nwhen { resource.program == "rm" };'
MODEL = {"id": "c-secrets", "name": "Block secret files", "actions": ["read_path"], "what": {"paths": ["*.env"]}}


async def _put(client, user, version, policy_id, body, etag):
    headers = {**bearer(user), **({"If-Match": etag} if etag is not None else {})}
    return await client.put(f"{BASE}/policy-sets/{version}/policies/{policy_id}", json=body, headers=headers)


@pytest.mark.asyncio
async def test_policy_level_saves_build_the_draft_deterministically_with_if_match(client, db):
    published = await publish(client, db, SEAT + "\n\n" + KEEP + "\n")
    admin = await make_user(db, admin=True)
    base = (await client.get(f"{BASE}/policy-sets/{published}", headers=bearer(admin))).json()
    assert (await client.get(f"{BASE}/policies", headers=bearer(admin))).json()["edit_target"] == {
        "version": published, "digest": base["digest"], "creates_draft": True}

    assert (await _put(client, admin, published, "c-secrets", {"model": MODEL}, None)).status_code == 428
    stale = await _put(client, admin, published, "c-secrets", {"model": MODEL}, "sha256:old")
    assert stale.status_code == 409 and stale.json()["detail"] == {"code": "policy_set_draft_conflict",
                                                                   "digest": base["digest"]}
    created = await _put(client, admin, published, "c-secrets", {"model": MODEL, "create": True}, f'"{base["digest"]}"')
    assert created.status_code == 200, created.text
    draft = created.json()["version"]
    assert draft["state"] == "draft" and draft["base_version"] == published
    assert draft["policies"] == "\n\n".join([KEEP, SEAT, render(_model(MODEL))]) + "\n", "sorted by @id"
    assert draft["policy_ids"] == ["a-keep", "b-seat", "c-secrets"]
    assert created.json()["policy"]["source"] == "builder" and created.json()["policy"]["model"]["id"] == "c-secrets"
    assert draft["test_report"]["ok"] is True

    again = await _put(client, admin, published, "x", {"model": {**MODEL, "id": "x"}}, base["digest"])
    assert again.status_code == 409 and again.json()["detail"]["code"] == "policy_set_draft_exists"
    exists = await _put(client, admin, draft["version"], "a-keep", {"cedar": KEEP, "create": True}, draft["digest"])
    assert exists.status_code == 409 and exists.json()["detail"]["code"] == "policy_id_exists"

    edited = await _put(client, admin, draft["version"], "a-keep",
                        {"cedar": KEEP.replace('"rm"', '"shred"')}, draft["digest"])
    assert edited.status_code == 200 and edited.json()["policy"]["source"] == "hand_written"
    second = edited.json()["version"]
    assert second["version"] == draft["version"] and '"shred"' in second["policies"]
    conflict = await _put(client, admin, draft["version"], "a-keep", {"cedar": KEEP}, draft["digest"])
    assert conflict.status_code == 409 and conflict.json()["detail"]["digest"] == second["digest"]

    renamed = await _put(client, admin, draft["version"], "c-secrets", {"model": {**MODEL, "id": "d-secrets"}},
                         second["digest"])
    assert renamed.json()["version"]["policy_ids"] == ["a-keep", "b-seat", "d-secrets"]
    third = renamed.json()["version"]

    removed = await client.delete(f"{BASE}/policy-sets/{draft['version']}/policies/b-seat",
                                  headers={**bearer(admin), "If-Match": third["digest"]})
    assert removed.status_code == 200 and removed.json()["version"]["policy_ids"] == ["a-keep", "d-secrets"]
    missing = await client.delete(f"{BASE}/policy-sets/{draft['version']}/policies/b-seat",
                                  headers={**bearer(admin), "If-Match": removed.json()["version"]["digest"]})
    assert missing.status_code == 404 and missing.json()["detail"]["code"] == "policy_not_found"


@pytest.mark.asyncio
async def test_policy_level_save_refusals(client, db):
    admin = await make_user(db, admin=True)
    empty = custom_digest("")
    target = (await client.get(f"{BASE}/policies", headers=bearer(admin))).json()["edit_target"]
    assert target == {"version": 0, "digest": empty, "creates_draft": True}
    first = await _put(client, admin, target["version"], "c-secrets", {"model": MODEL}, target["digest"])
    assert first.status_code == 200 and first.json()["version"]["version"] == 1, "version 0 is the empty set"
    draft = first.json()["version"]
    assert (await _put(client, admin, 0, "y", {"model": {**MODEL, "id": "y"}}, empty)).status_code == 409

    for body, code in [({"model": {"id": "z", "actions": []}}, "policy_builder_model_invalid"),
                       ({"cedar": SEAT + "\n" + KEEP}, "policy_cedar_statement_invalid"),
                       ({"cedar": "forbid (principal, action, resource);"}, "policy_cedar_statement_invalid"),
                       ({"model": MODEL, "cedar": SEAT}, "policy_edit_body_invalid")]:
        refused = await _put(client, admin, draft["version"], "z", body, draft["digest"])
        assert refused.status_code == 422 and refused.json()["detail"]["code"] == code, body
    permit = await _put(client, admin, draft["version"], "z",
                        {"cedar": '@id("z")\npermit (principal, action, resource);'}, draft["digest"])
    assert permit.status_code == 422 and permit.json()["detail"]["code"] == "policy_set_invalid"

    submitted = await client.post(f"{BASE}/policy-sets/{draft['version']}/submit", headers=bearer(admin))
    assert submitted.status_code == 200
    assert (await client.get(f"{BASE}/policies", headers=bearer(admin))).json()["edit_target"] is None
    frozen = await _put(client, admin, draft["version"], "z", {"model": {**MODEL, "id": "z"}}, draft["digest"])
    assert frozen.status_code == 409 and frozen.json()["detail"]["code"] == "policy_set_version_not_editable"


@pytest.mark.asyncio
async def test_the_read_model_reopens_only_policies_the_builder_can_parse(client, db):
    model = _model(MODEL)
    canonical = render(model)
    hand_edited = canonical.replace("when {", "when  {").replace('"c-secrets"', '"c-secrets-2"')
    await publish(client, db, canonical + "\n\n" + hand_edited + "\n")
    admin = await make_user(db, admin=True)
    items = {item["id"]: item for item in (await client.get(f"{BASE}/policies", headers=bearer(admin))).json()["items"]}
    assert items["c-secrets"]["source"] == "builder" and items["c-secrets"]["model"] == model.to_json()
    assert "".join(seg["text"] for seg in items["c-secrets"]["sentence"]) == (
        "Block coding agents of everyone from reading files matching *.env in all Workspaces.")
    assert items["c-secrets-2"]["source"] == "hand_written" and items["c-secrets-2"]["model"] is None
