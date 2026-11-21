"""Builder UX: content policies in the guided builder — model rules, round trip, sentence, template save."""

from __future__ import annotations

import uuid

import pytest

from app.models import Project
from app.services.policy_engine import catalog
from app.services.policy_engine.builder import render
from app.services.policy_engine.builder_model import model_from_json
from app.services.policy_engine.builder_parse import parse
from app.services.policy_engine.builder_sentence import sentence
from app.services.policy_engine.custom_policies import custom_digest
from tests.policy_engine_support import BASE, bearer, make_user

CUSTOM = {"custom.customer_ref": "confidential_identifier"}
ROUTED = {"id": "pii-routed", "actions": ["call_model"],
          "content": {"detectors": ["email", "phone"], "sticky": True, "incomplete": True},
          "outcome": {"kind": "mask_reroute", "reroute_to": "company-model", "mask_style": "last4"}}


def _model(raw, custom=None):
    model, issues = model_from_json(raw, CUSTOM if custom is None else custom)
    assert model is not None, issues
    return model


def _codes(raw, custom=None):
    _, issues = model_from_json(raw, CUSTOM if custom is None else custom)
    return {(issue["path"], issue["code"]) for issue in issues}


@pytest.mark.parametrize(("raw", "expected"), [
    ({"id": "x", "actions": ["receive_tool_result"], "content": {"detectors": ["email"]},
      "outcome": {"kind": "reroute", "reroute_to": "m"}}, ("outcome.kind", "builder_outcome_invalid")),
    ({"id": "x", "actions": ["call_model"], "content": {"detectors": ["custom.unknown"]}},
     ("content.detectors[0]", "builder_detector_unknown")),
    ({"id": "x", "actions": ["call_model"], "content": {"detectors": ["passport"]}},
     ("content.detectors[0]", "builder_detector_unknown")),
    ({"id": "x", "actions": ["call_model"], "content": {"detectors": ["email"], "sticky": True},
      "outcome": {"kind": "mask"}}, ("content.sticky", "builder_outcome_invalid")),
    ({"id": "x", "actions": ["call_model"], "content": {"detectors": ["email"]},
      "outcome": {"kind": "reroute", "reroute_to": "m", "approved_except": True}},
     ("outcome.approved_except", "builder_outcome_invalid")),
    ({"id": "x", "actions": ["receive_tool_result"], "content": {"detectors": ["email"]},
      "outcome": {"kind": "mask", "approved_except": True}}, ("outcome.approved_except", "builder_outcome_invalid")),
    ({"id": "x", "actions": ["call_model"], "content": {"detectors": ["email"]}, "outcome": {"kind": "reroute"}},
     ("outcome.reroute_to", "builder_reroute_target_required")),
    ({"id": "x", "actions": ["call_model", "receive_tool_result"], "content": {"detectors": ["email"]}},
     ("actions", "builder_content_action_invalid")),
    ({"id": "x", "actions": ["call_model"], "outcome": {"kind": "mask"}},
     ("content.detectors", "builder_content_detectors_required")),
    ({"id": "x", "actions": ["call_model"], "content": {"detectors": ["email"]}, "what": {"models": ["a"]}},
     ("what.models", "builder_block_not_applicable")),
    ({"id": "x", "actions": ["call_model"], "content": {"detectors": ["email"]}, "outcome": {"kind": "hide"}},
     ("outcome.kind", "builder_value_invalid")),
])
def test_the_reader_refuses_content_rules(raw, expected):
    assert expected in _codes(raw)


def test_unused_outcome_fields_are_normalized():
    model = _model({"id": "x", "actions": ["call_model"], "content": {"detectors": ["email"]},
                    "outcome": {"kind": "mask", "reroute_to": "m"}})
    assert model.outcome.reroute_to == "" and model.outcome.mask_style == "type_token"
    assert model.content.categories == (), "categories are kept only where the Cedar names them"
    assert _model(ROUTED).content.categories == ("pii",)


@pytest.mark.parametrize("raw", [
    ROUTED,
    {"id": "b", "actions": ["call_model"], "content": {"detectors": ["secrets"]}},
    {"id": "m", "actions": ["call_model"], "content": {"detectors": ["email", "iban"]},
     "outcome": {"kind": "mask", "approved_except": True}, "where": {"classification_at_least": "internal"}},
    {"id": "r", "actions": ["call_model"], "content": {"detectors": ["custom.customer_ref", "iban"], "sticky": True},
     "outcome": {"kind": "reroute", "reroute_to": "private-model"}, "where": {"workspaces": ["w1"]}},
    {"id": "t", "actions": ["receive_tool_result"], "content": {"detectors": ["phone"]},
     "outcome": {"kind": "mask", "mask_style": "last4"}, "who": {"except_admins": True}},
])
def test_every_outcome_round_trips(raw):
    model = _model(raw)
    text = render(model)
    assert parse(text) == model, "parse(render(m)) == m, a custom detector's category read back from the text"
    assert render(parse(text)) == text


def test_the_mask_and_route_policy_renders_the_approved_shape():
    assert render(_model(ROUTED)) == (
        '@id("pii-routed")\n@builder("1")\n@obligation("mask_reroute")\n@reroute_to("company-model")\n'
        '@mask("email,phone")\n@mask_style("last4")\n'
        'forbid (principal, action == Action::"call_model", resource)\n'
        'when { context.content.detected.containsAny(["email", "phone"]) || '
        '(context.content.scanned && !context.content.complete) || '
        '(principal is AgentSession && principal.sensitive.containsAny(["pii"])) }\n'
        'unless { context.route == "governed" && resource.approved_for.containsAll(["pii"]) && '
        '!context.content.detected.containsAny(["email", "phone"]) };')


def test_a_hand_edited_content_policy_is_not_reopened_by_the_builder():
    text = render(_model(ROUTED))
    assert parse(text.replace('@mask("email,phone")', '@mask("email")')) is None
    assert parse(text.replace('["pii"]))', '["secrets"]))')) is None, "sticky and route categories differ"


class _Names:
    def group(self, name):
        return name

    def user(self, user_id):
        return user_id


def _sentence(raw) -> str:
    return "".join(segment["text"] for segment in sentence(_model(raw), _Names()))


def test_sentences_follow_the_outcome():
    assert _sentence(ROUTED) == (
        "When a model request contains email addresses or phone numbers (or could not be fully "
        "scanned), mask them and route the request to company-model, for everyone in all Workspaces. The "
        "conversation stays on company-model until it is cleared. If company-model cannot take the request, it is "
        "blocked.")
    assert _sentence({"id": "m", "actions": ["call_model"], "content": {"detectors": ["email", "phone", "iban"]},
                      "outcome": {"kind": "mask", "approved_except": True}}) == (
        "When a model request contains email addresses, phone numbers or IBANs, mask them, for everyone in all "
        "Workspaces, except on models approved for personal data.")
    assert _sentence({"id": "h", "actions": ["call_model"], "conditions": {"route": "seat"},
                      "content": {"detectors": ["custom.customer_ref"]}}) == (
        "When a model request on the seat route contains customer ref, block it, for everyone in all Workspaces.")


@pytest.mark.asyncio
async def test_a_rendered_template_saves_with_an_approved_alias(client, db):
    from tests.content_detection.content_obligations_support import _governed_alias
    from tests.model_gateway.conftest import ALIAS

    admin = await make_user(db, admin=True)
    workspace = Project(id=str(uuid.uuid4()), name=f"ws-{uuid.uuid4().hex[:6]}", config={}, is_active=True)
    db.add(workspace)
    await db.commit()
    await _governed_alias(db, workspace.id, approved=["pii"])
    aliases = (await client.get(f"{BASE}/catalog/entities", headers=bearer(admin))).json()["model_aliases"]
    assert {"alias": ALIAS, "approved_for": ["pii"]}.items() <= next(
        item for item in aliases if item["alias"] == ALIAS).items(), "the Outcome step's approved-model chips"

    template = catalog.template_info("workspace-identifiers-approved-model")
    model = {"id": "personal-data-routed", "template": template["id"], **template["model"]}
    model["content"] = {**model["content"], "detectors": ["email", "phone"]}  # the template's placeholders
    model["outcome"] = {**model["outcome"], "reroute_to": ALIAS}
    preview = (await client.post(f"{BASE}/policy-builder/render", json={"model": model}, headers=bearer(admin))).json()
    assert preview["valid"] is True, preview["issues"]
    saved = await client.put(f"{BASE}/policy-sets/0/policies/personal-data-routed", json={"model": model, "create": True},
                             headers={**bearer(admin), "If-Match": custom_digest("")})
    assert saved.status_code == 200, saved.text
    policy = saved.json()["policy"]
    assert policy["source"] == "builder" and policy["model"]["outcome"]["reroute_to"] == ALIAS

    unknown = {**model, "content": {**model["content"], "detectors": ["custom.not_in_this_set"]}}
    refused = (await client.post(f"{BASE}/policy-builder/render", json={"model": unknown},
                                 headers=bearer(admin))).json()
    assert refused["valid"] is False and refused["issues"][0]["code"] == "builder_detector_unknown"
