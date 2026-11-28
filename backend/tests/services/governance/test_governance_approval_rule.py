"""The platform approval rule: four-eyes by default, single-admin self-approval on request."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.models import AuditLog
from app.services.governance import four_eyes
from app.services.governance.approval_rule import AUDIT_APPROVAL_RULE_UPDATED, set_approval_rule
from app.services.governance.four_eyes import SELF_APPROVAL_AUDIT_ACTION
from app.services.prompt_catalog import lifecycle as prompt_lifecycle
from tests.policy_engine_support import BASE, bearer, make_user
from tests.support.model_policy_support import four_eyes_settings

RULE_URL = "/api/v1/admin/governance/approval-rule"
FORBID = '@id("no-rollout-restart")\nforbid (principal, action == Action::"run_command", resource)\n' \
         'when { resource.prefixes.contains("kubectl rollout restart") };\n'


@pytest.fixture(autouse=True)
def no_dev_exception(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(four_eyes, "get_settings", lambda: four_eyes_settings(dev_self_approval=False))


async def _self_audits(db) -> list[AuditLog]:
    return list((await db.execute(select(AuditLog).where(AuditLog.action == SELF_APPROVAL_AUDIT_ACTION))).scalars())


@pytest.mark.asyncio
async def test_the_rule_defaults_to_four_eyes_is_platform_admin_only_and_audited(client, db):
    admin, member = await make_user(db, admin=True), await make_user(db, admin=False)
    current = (await client.get(RULE_URL, headers=bearer(member))).json()
    assert (current["rule"], current["self_approval_allowed"]) == ("four_eyes", False)
    assert [option["value"] for option in current["options"]] == ["four_eyes", "single_admin"]

    assert (await client.put(RULE_URL, json={"rule": "single_admin"}, headers=bearer(member))).status_code == 403
    invalid = await client.put(RULE_URL, json={"rule": "nobody"}, headers=bearer(admin))
    assert invalid.status_code == 422 and invalid.json()["detail"]["code"] == "approval_rule_invalid"
    changed = await client.put(RULE_URL, json={"rule": "single_admin"}, headers=bearer(admin))
    assert changed.status_code == 200
    assert (changed.json()["rule"], changed.json()["self_approval_allowed"]) == ("single_admin", True)

    audits = list((await db.execute(select(AuditLog).where(AuditLog.action == AUDIT_APPROVAL_RULE_UPDATED))).scalars())
    assert [(row.user_id, row.details) for row in audits] == [(admin, {"previous": "four_eyes", "rule": "single_admin"})]


@pytest.mark.asyncio
async def test_policy_sets_publish_in_one_step_only_under_the_single_admin_rule(client, db):
    author = await make_user(db, admin=True)
    version = (await client.post(f"{BASE}/policy-sets", json={"policies": FORBID}, headers=bearer(author))).json()
    number = version["version"]
    assert (await client.post(f"{BASE}/policy-sets/{number}/submit", headers=bearer(author))).status_code == 200

    refused = await client.post(f"{BASE}/policy-sets/{number}/publish", json={"self_approve": True},
                                headers=bearer(author))
    assert refused.status_code == 409 and refused.json()["detail"]["code"] == "policy_set_self_approval"

    await client.put(RULE_URL, json={"rule": "single_admin"}, headers=bearer(author))
    published = await client.post(f"{BASE}/policy-sets/{number}/publish", json={"self_approve": True},
                                  headers=bearer(author))
    assert published.status_code == 200, published.text
    assert published.json()["approval_gate"]["approval_mode"] == "self"
    history = (await client.get(f"{BASE}/policy-sets", headers=bearer(author))).json()
    assert next(row for row in history["items"] if row["version"] == number)["approval_mode"] == "self"
    assert [row.resource_type for row in await _self_audits(db)] == ["policy_set_version"]


@pytest.mark.asyncio
async def test_prompt_templates_self_approve_only_under_the_single_admin_rule(db, auth_user):
    _template, version = await prompt_lifecycle.create_draft(
        db, key="secure_work.gateway.deny.path_denied", scope_type="global", scope_id=None,
        body="Reviewed: {tool} is outside the allowed paths ({rule_id}).", change_note="", user=auth_user,
    )
    await prompt_lifecycle.submit_for_review(db, version_id=version.id, user=auth_user)
    with pytest.raises(prompt_lifecycle.PromptCatalogRefusal) as refused:
        await prompt_lifecycle.publish(db, version_id=version.id, user=auth_user, approval_id=None, self_approve=True)
    assert refused.value.code == "self_approval_not_allowed"

    await set_approval_rule(db, rule="single_admin", actor_id=auth_user.id)
    published, gate = await prompt_lifecycle.publish(
        db, version_id=version.id, user=auth_user, approval_id=None, self_approve=True
    )
    assert (published.state, gate["approval_mode"]) == ("published", "self")
    assert [row.resource_type for row in await _self_audits(db)] == ["prompt_template_version"]
