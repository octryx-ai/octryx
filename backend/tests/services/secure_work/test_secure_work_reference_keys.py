"""Contract: reference keys, lists, item-bound targets, mask round-trip, build links."""

# ruff: noqa: F811  (the shared ``world`` fixture is imported, then requested by name)
from __future__ import annotations

import uuid

import pytest

from app.models import WorkCicdPipelineTrace
from app.services.secure_work.config_visibility import MASK, is_secret_field, mask_field, unmasked
from tests.services.secure_work.secure_work_families_support import world  # noqa: F401  (fixture)
from tests.services.secure_work.test_secure_work_reference_scope import API


async def test_r11_1_own_trace_alias_still_links(world, db):
    api, item, rows = world["api"], world["item_a"], world["rows"]
    own_provider = rows["cicd-providers"]["a"].id
    trace = WorkCicdPipelineTrace(work_item_id=item, provider_config_id=own_provider, job_name="a",
                                  created_by=world["admin"].id)
    db.add(trace)
    await db.commit()
    found = await api.post(f"{API}/work-items/{item}/cicd-findings",
                           json={"cicd_pipeline_trace_id": trace.id, "title": "x"})
    assert found.status_code == 200, found.text
    world["state"]["user"] = world["admin"]
    refused = await api.post(f"{API}/work-items/{item}/cicd-findings",
                             json={"cicd_pipeline_trace_id": world["trace_b"], "title": "x"})
    assert refused.status_code == 403


async def test_r11_2_a_non_string_reference_answers_like_a_missing_row(world):
    api, item = world["api"], world["item_a"]
    answers = [await api.post(f"{API}/work-items/{item}/cicd-findings", json={"cicd_pipeline_trace_id": value,
                                                                               "title": "x"})
               for value in ([world["trace_b"]], {"id": world["trace_b"]}, str(uuid.uuid4()))]
    assert {answer.status_code for answer in answers} == {404}
    assert answers[0].json() == answers[1].json() == answers[2].json()


@pytest.mark.parametrize(("key", "secret"), [
    ("credential_ref", True), ("api_key", True), ("api_key_ref", True), ("apiKey", True), ("signing_key", True),
    ("key", True), ("ssh_private_key", True), ("auth_header", True), ("Authorization", True), ("hmac", True),
    ("webhook_hmac_secret", True), ("is_private", True), ("project_key", False), ("jira_project_keys", False),
    ("required_stage_keys", False), ("author", False), ("base_url", False), ("name", False),
])
def test_r11_5_secret_field_markers(key, secret):
    assert is_secret_field(key) is secret
    assert mask_field(key, True) is True and mask_field(key, 3) == 3, "flags and numbers are never secrets"


def test_r11_4_unmasked_restores_only_values_left_masked():
    stored = {"credential_ref": "cr", "webhook": {"signing_key": "s", "enabled": False},
              "secret_references": ["a", "b"], "base_url": "https://u:p@h.test", "name": "n"}
    sent = {"credential_ref": MASK, "webhook": {"signing_key": MASK, "enabled": True},
            "secret_references": [MASK, "c"], "base_url": "https://***@h.test", "name": "m", "new": MASK}
    assert unmasked(sent, stored) == {"credential_ref": "cr", "webhook": {"signing_key": "s", "enabled": True},
                                      "secret_references": ["a", "c"], "base_url": "https://u:p@h.test",
                                      "name": "m", "new": MASK}


@pytest.mark.parametrize(("route", "key", "pad"), [
    ("cicd-pipeline-traces", "provider_config_id", "{} "),
    ("cicd-findings", "provider_config_id", "{} "),
    ("cicd-findings", "cicd_pipeline_trace_id", "\t{}"),
    ("cicd-findings", "pipeline_trace_id", " {}\n"),
])
async def test_rf1_padded_foreign_ids_are_trimmed_before_the_check(world, route, key, pad):
    rows = world["rows"]
    foreign = {"cicd_build_id": world["build_b"], "provider_config_id": rows["cicd-providers"]["b"].id,
               "cicd_pipeline_trace_id": world["trace_b"], "pipeline_trace_id": world["trace_b"]}[key]
    world["state"]["user"] = world["admin"]
    sent = await world["api"].post(f"{API}/work-items/{world['item_a']}/{route}",
                                   json={key: pad.format(foreign), "title": "x"})
    assert sent.status_code == 403, sent.text


async def test_rf1_odd_body_id_types_are_422(world):
    api, rows, item = world["api"], world["rows"], world["item_a"]
    world["state"]["user"] = world["admin"]
    profile_b = rows["repository-profiles"]["b"].id
    preview = f"{API}/coding-pipelines/checks/preview"
    for odd in ([item], {"id": item}, 123):
        assert (await api.post(preview, json={"work_item_id": odd, "repository_profile_id": profile_b})
                ).status_code == 422, odd
    assert (await api.post(preview, json={"change_unit_id": [world["unit_b"]]})).status_code == 422


def test_rf3_an_unmatched_mask_is_dropped_never_stored():
    assert unmasked({"refs": [MASK, MASK]}, {"refs": []}) == {"refs": []}
