"""The policy-engine admin API — authz, custom-policy validation, governed versions, four-eyes publish."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.config import get_settings
from app.models import Approval, AuditLog, PolicySetVersion, SystemConfig
from app.models.runtime.governed_revision import ImmutableRevisionError
from app.services.policy_engine.runtime import MODE_CONFIG_KEY, current_runtime
from tests.policy_engine_support import BASE, approve, bearer, make_user

FORBID = '@id("no-rollout-restart")\nforbid (principal, action == Action::"run_command", resource)\n' \
         'when { resource.prefixes.contains("kubectl rollout restart") };\n'
FORBID_V2 = FORBID.replace("no-rollout-restart", "no-rollout-restart-v2")


async def _draft(client, user_id: str, policies: str = FORBID) -> dict:
    response = await client.post(f"{BASE}/policy-sets", json={"policies": policies, "note": "n"},
                                 headers=bearer(user_id))
    assert response.status_code == 201, response.text
    return response.json()


async def _submitted(client, db, author: str, policies: str = FORBID) -> tuple[int, str]:
    version = (await _draft(client, author, policies))["version"]
    response = await client.post(f"{BASE}/policy-sets/{version}/submit", headers=bearer(author))
    assert response.status_code == 200, response.text
    return version, response.json()["governance_approval_id"]


@pytest.mark.asyncio
async def test_every_endpoint_is_platform_admin_only(client, db):
    member = await make_user(db, admin=False)
    for method, path in [("get", "/status"), ("put", "/mode"), ("get", "/schema"), ("get", "/baseline"),
                         ("get", "/decisions"), ("post", "/validate"), ("get", "/policy-sets"),
                         ("post", "/policy-sets"), ("get", "/policy-sets/1"), ("post", "/policy-sets/1/publish")]:
        kwargs = {"json": {"mode": "off", "policies": ""}} if method in {"put", "post"} else {}
        response = await getattr(client, method)(f"{BASE}{path}", headers=bearer(member), **kwargs)
        assert response.status_code == 403, (path, response.status_code)
    assert (await client.get(f"{BASE}/status")).status_code == 401


@pytest.mark.asyncio
@pytest.mark.parametrize(("policies", "code"), [
    ('permit (principal, action, resource);', "policy_id_required"),
    ('@id("ok") permit (principal, action, resource);', "permit_not_allowed"),
    ('@id("platform:x") forbid (principal, action, resource);', "policy_id_reserved"),
    ('@id("workspace:x") forbid (principal, action, resource);', "policy_id_reserved"),
    ('@id("a b") forbid (principal, action, resource);', "policy_id_invalid"),
    ('@id("d") forbid (principal, action, resource);\n@id("d") forbid (principal, action, resource);',
     "policy_id_duplicate"),
    ('@id("t") forbid (principal, action == Action::"run_command", resource) when { resource.nope };', "schema"),
    ('@id("t") forbid (principal, action, resource', "schema"),
])
async def test_custom_policies_that_do_not_validate_are_refused_with_their_issue(client, db, policies, code):
    admin = await make_user(db, admin=True)
    response = await client.post(f"{BASE}/policy-sets", json={"policies": policies}, headers=bearer(admin))
    assert response.status_code == 422
    assert code in {issue["code"] for issue in response.json()["detail"]["issues"]}
    check = (await client.post(f"{BASE}/validate", json={"policies": policies}, headers=bearer(admin))).json()
    assert check["valid"] is False and code in {issue["code"] for issue in check["issues"]}
    assert (await db.execute(select(PolicySetVersion))).scalars().first() is None


@pytest.mark.asyncio
async def test_templates_are_refused(client, db):
    admin = await make_user(db, admin=True)
    template = '@id("t") forbid (principal == ?principal, action, resource);'
    response = await client.post(f"{BASE}/policy-sets", json={"policies": template}, headers=bearer(admin))
    assert response.status_code == 422 and response.json()["detail"]["code"] == "policy_set_templates_not_allowed"


@pytest.mark.asyncio
async def test_four_eyes_publish_retires_the_previous_version_and_reloads_the_runtime(client, db):
    author, reviewer = await make_user(db, admin=True), await make_user(db, admin=True)
    version, approval_id = await _submitted(client, db, author)
    early = await client.post(f"{BASE}/policy-sets/{version}/publish",
                              json={"governance_approval_id": approval_id}, headers=bearer(author))
    assert early.status_code == 409 and early.json()["detail"]["code"] == "policy_set_approval_not_approved"
    await approve(db, approval_id, reviewer)
    published = await client.post(f"{BASE}/policy-sets/{version}/publish",
                                  json={"governance_approval_id": approval_id}, headers=bearer(author))
    assert published.status_code == 200, published.text
    body = published.json()
    assert body["state"] == "published" and body["baseline_digest"].startswith("sha256:")
    assert body["approval_gate"]["approved_by"] == reviewer
    assert current_runtime().custom_version == version
    assert current_runtime().custom_ids == frozenset({"no-rollout-restart"})

    second, second_approval = await _submitted(client, db, author, FORBID_V2)
    await approve(db, second_approval, reviewer)
    assert (await client.post(f"{BASE}/policy-sets/{second}/publish", json={"governance_approval_id": second_approval},
                              headers=bearer(reviewer))).status_code == 200
    states = {row.version: row.state for row in (await db.execute(select(PolicySetVersion))).scalars()}
    assert states == {version: "retired", second: "published"}
    actions = set((await db.execute(select(AuditLog.action).where(AuditLog.action.like("policy_engine.%")))).scalars())
    assert {"policy_engine.policy_set_published", "policy_engine.policy_set_retired",
            "policy_engine.policy_set_submitted", "policy_engine.policy_set_draft_saved"} <= actions


@pytest.mark.asyncio
async def test_the_dev_exception_allows_self_approval_like_every_four_eyes_gate(client, db, monkeypatch):
    author = await make_user(db, admin=True)
    monkeypatch.setattr(get_settings(), "four_eyes_dev_self_approval", True)
    monkeypatch.setattr(get_settings(), "runtime_profile", "local")
    monkeypatch.setattr(get_settings(), "cors_allowed_origins", "http://localhost:3000")
    version, approval_id = await _submitted(client, db, author)
    await approve(db, approval_id, author)
    response = await client.post(f"{BASE}/policy-sets/{version}/publish",
                                 json={"governance_approval_id": approval_id}, headers=bearer(author))
    # One central rule (services/governance/four_eyes); the dev flag implies self-approval.
    assert response.status_code == 200 and response.json()["approval_gate"]["approval_mode"] == "self"


@pytest.mark.asyncio
async def test_the_author_cannot_approve_a_version_someone_else_submitted(client, db):
    author, submitter = await make_user(db, admin=True), await make_user(db, admin=True)
    version = (await _draft(client, author))["version"]
    approval_id = (await client.post(f"{BASE}/policy-sets/{version}/submit",
                                     headers=bearer(submitter))).json()["governance_approval_id"]
    await approve(db, approval_id, author)
    response = await client.post(f"{BASE}/policy-sets/{version}/publish",
                                 json={"governance_approval_id": approval_id}, headers=bearer(submitter))
    assert response.json()["detail"]["code"] == "policy_set_self_approval"


@pytest.mark.asyncio
async def test_the_dev_flag_self_approval_is_audited_on_publish(client, db, monkeypatch):
    author = await make_user(db, admin=True)
    monkeypatch.setattr(get_settings(), "four_eyes_dev_self_approval", True)
    version, approval_id = await _submitted(client, db, author)
    await approve(db, approval_id, author)
    response = await client.post(f"{BASE}/policy-sets/{version}/publish",
                                 json={"governance_approval_id": approval_id}, headers=bearer(author))
    assert response.status_code == 200 and response.json()["approval_gate"]["single_admin_self_approval"] is True
    audited = (await db.execute(select(AuditLog).where(
        AuditLog.action == "governance.four_eyes.dev_self_approval"))).scalars().all()
    assert len(audited) == 1 and audited[0].user_id == author


@pytest.mark.asyncio
async def test_the_approver_must_be_a_platform_admin_and_the_approval_must_match(client, db):
    author, member = await make_user(db, admin=True), await make_user(db, admin=False)
    version, approval_id = await _submitted(client, db, author)
    await approve(db, approval_id, member)
    response = await client.post(f"{BASE}/policy-sets/{version}/publish",
                                 json={"governance_approval_id": approval_id}, headers=bearer(author))
    assert response.json()["detail"]["code"] == "policy_set_approver_not_platform_admin"
    other = Approval(requested_by=author, action="policy_set.publish:x:y", status="approved", approved_by=member)
    db.add(other)
    await db.commit()
    mismatched = await client.post(f"{BASE}/policy-sets/{version}/publish",
                                   json={"governance_approval_id": other.id}, headers=bearer(author))
    assert mismatched.json()["detail"]["code"] == "policy_set_approval_mismatched"
    missing = await client.post(f"{BASE}/policy-sets/{version}/publish", json={}, headers=bearer(author))
    assert missing.json()["detail"]["code"] == "policy_set_approval_required"


@pytest.mark.asyncio
async def test_only_drafts_change_and_published_rows_are_immutable(client, db):
    author, reviewer = await make_user(db, admin=True), await make_user(db, admin=True)
    version, approval_id = await _submitted(client, db, author)
    edit = await client.put(f"{BASE}/policy-sets/{version}", json={"policies": FORBID_V2},
                            headers={**bearer(author), "If-Match": "sha256:any"})
    assert edit.status_code == 409 and edit.json()["detail"]["code"] == "policy_set_version_not_draft"
    await approve(db, approval_id, reviewer)
    await client.post(f"{BASE}/policy-sets/{version}/publish", json={"governance_approval_id": approval_id},
                      headers=bearer(author))
    row = (await db.execute(select(PolicySetVersion).where(PolicySetVersion.version == version))).scalar_one()
    row.policies_text = FORBID_V2
    with pytest.raises(ImmutableRevisionError):
        await db.flush()
    await db.rollback()


@pytest.mark.asyncio
async def test_rollback_creates_a_reviewable_draft_that_can_be_withdrawn(client, db):
    author, reviewer = await make_user(db, admin=True), await make_user(db, admin=True)
    version, approval_id = await _submitted(client, db, author)
    await approve(db, approval_id, reviewer)
    await client.post(f"{BASE}/policy-sets/{version}/publish", json={"governance_approval_id": approval_id},
                      headers=bearer(author))
    rollback = await client.post(f"{BASE}/policy-sets/{version}/rollback", headers=bearer(author))
    assert rollback.status_code == 201
    assert rollback.json()["state"] == "draft" and rollback.json()["policies"] == FORBID
    assert rollback.json()["base_version"] == version
    listing = (await client.get(f"{BASE}/policy-sets", headers=bearer(author))).json()
    assert [item["version"] for item in listing["items"]] == [version + 1, version]
    assert "policies" not in listing["items"][0]
    withdrawn = await client.post(f"{BASE}/policy-sets/{version + 1}/retire", headers=bearer(author))
    assert withdrawn.status_code == 200 and withdrawn.json()["state"] == "retired"
    assert current_runtime().custom_version == version  # withdrawing a draft leaves the published set


@pytest.mark.asyncio
async def test_mode_is_stored_audited_and_enforce_is_not_available_yet(client, db):
    admin = await make_user(db, admin=True)
    response = await client.put(f"{BASE}/mode", json={"mode": "off"}, headers=bearer(admin))
    assert response.status_code == 200 and response.json()["mode"] == "off"
    assert (await db.get(SystemConfig, MODE_CONFIG_KEY)).value == "off"
    assert current_runtime().mode == "off"
    enforce = await client.put(f"{BASE}/mode", json={"mode": "enforce"}, headers=bearer(admin))
    assert enforce.status_code == 409 and enforce.json()["detail"]["code"] == "policy_engine_enforce_not_ready"
    bogus = await client.put(f"{BASE}/mode", json={"mode": "loud"}, headers=bearer(admin))
    assert bogus.status_code == 422 and bogus.json()["detail"]["code"] == "policy_engine_mode_invalid"
    audited = (await db.execute(select(AuditLog).where(AuditLog.action == "policy_engine.mode_updated"))).scalars()
    assert [row.details for row in audited] == [{"previous": "shadow", "mode": "off"}]


@pytest.mark.asyncio
async def test_status_schema_and_baseline_views(client, db):
    admin = await make_user(db, admin=True)
    status = (await client.get(f"{BASE}/status", headers=bearer(admin))).json()
    assert status["mode"] == "shadow" and status["engine"]["available"] is True
    assert status["custom"] == {"version": None, "digest": None, "valid": True, "fallback": None}
    assert status["custom_fallbacks"] == {}
    schema = (await client.get(f"{BASE}/schema", headers=bearer(admin))).json()
    assert "entity Workspace" in schema["schema"] and "run_command" in schema["actions"]
    baseline = (await client.get(f"{BASE}/baseline", headers=bearer(admin))).json()
    assert baseline["digest"] == status["baseline"]["digest"]
    assert '@id("platform:seat-permit")' in baseline["policies"]
