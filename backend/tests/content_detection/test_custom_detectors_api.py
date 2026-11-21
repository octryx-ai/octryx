"""Custom detectors in the governed policy set: API, digest, four-eyes, rollback, preview."""

from __future__ import annotations

import logging
import uuid

import pytest
from sqlalchemy import select

from app.models import AuditLog, PolicySetVersion, Project
from app.services.policy_engine.custom_policies import custom_digest
from app.services.policy_engine.runtime import current_runtime
from tests.policy_engine_support import BASE, approve, bearer, make_user

PATTERN = r"\bQX-\d{4}-\d{6}\b"
DETECTOR = {"id": "custom.case_ref", "label": "Case reference", "category": "contracts", "pattern": PATTERN,
            "context_words": ["case"], "mask_style": "last4"}
CATEGORY = {"id": "contracts", "label": "Contracts"}
USES_DETECTOR = ('@id("names-case-ref")\nforbid (principal, action == Action::"call_tool", resource)\n'
                 'when { resource.name == "custom.case_ref" };')


async def _put(client, user, version, digest, body):
    return await client.put(f"{BASE}/policy-sets/{version}/detectors", json=body,
                            headers={**bearer(user), "If-Match": digest})


async def _first_draft(client, admin):
    response = await _put(client, admin, 0, custom_digest(""), {"categories": [CATEGORY], "detectors": [DETECTOR]})
    assert response.status_code == 200, response.text
    return response.json()


@pytest.mark.asyncio
async def test_endpoints_are_platform_admin_only(client, db):
    member = await make_user(db, admin=False)
    for method, path in [("get", "/content-detectors"), ("get", "/policy-sets/1/detectors"),
                         ("put", "/policy-sets/1/detectors"), ("post", "/content-detectors/preview")]:
        kwargs = {"json": {}} if method in ("put", "post") else {}
        response = await getattr(client, method)(f"{BASE}{path}", headers=bearer(member), **kwargs)
        assert response.status_code == 403, (method, path)


@pytest.mark.asyncio
async def test_detectors_saved_into_a_new_draft_with_their_own_digest_and_audit(client, db):
    admin = await make_user(db, admin=True)
    draft = await _first_draft(client, admin)
    assert draft["state"] == "draft" and draft["policies"] == ""
    assert draft["digest"] != custom_digest("")
    assert draft["content_detectors"]["detectors"][0]["id"] == "custom.case_ref"
    audit = (await db.execute(select(AuditLog).where(
        AuditLog.action == "policy_engine.content_detectors_saved"))).scalars().one()
    assert audit.details["detectors"] == ["custom.case_ref"] and audit.details["categories"] == ["contracts"]
    assert PATTERN not in str(audit.details)

    stale = await _put(client, admin, draft["version"], custom_digest(""), {"detectors": []})
    assert stale.status_code == 409 and stale.json()["detail"]["code"] == "policy_set_draft_conflict"
    missing = await client.put(f"{BASE}/policy-sets/{draft['version']}/detectors", json={},
                               headers=bearer(admin))
    assert missing.status_code == 428


@pytest.mark.asyncio
async def test_invalid_definitions_and_unknown_workspace_are_refused(client, db):
    admin = await make_user(db, admin=True)
    bad = await _put(client, admin, 0, custom_digest(""), {"detectors": [{**DETECTOR, "pattern": "(a+)+"}]})
    assert bad.status_code == 422
    assert {item["code"] for item in bad.json()["detail"]["issues"]} >= {"pattern_unsafe", "detector_category_unknown"}
    unknown = await _put(client, admin, 0, custom_digest(""), {"categories": [CATEGORY], "detectors": [
        {**DETECTOR, "workspace_id": str(uuid.uuid4())}]})
    assert unknown.status_code == 422 and unknown.json()["detail"]["issues"][0]["code"] == "workspace_unknown"
    assert (await db.execute(select(PolicySetVersion))).first() is None


@pytest.mark.asyncio
async def test_policy_edits_keep_detectors_through_publish_new_draft_and_rollback(client, db):
    author, reviewer = await make_user(db, admin=True), await make_user(db, admin=True)
    draft = await _first_draft(client, author)
    saved = await client.put(f"{BASE}/policy-sets/{draft['version']}/policies/names-case-ref",
                             json={"cedar": USES_DETECTOR}, headers={**bearer(author), "If-Match": draft["digest"]})
    assert saved.status_code == 200, saved.text
    version = saved.json()["version"]["version"]
    row = (await db.execute(select(PolicySetVersion).where(PolicySetVersion.version == version))).scalar_one()
    await db.refresh(row)
    assert row.content_detectors["detectors"][0]["id"] == "custom.case_ref"

    submitted = await client.post(f"{BASE}/policy-sets/{version}/submit", headers=bearer(author))
    await approve(db, submitted.json()["governance_approval_id"], reviewer)
    published = await client.post(f"{BASE}/policy-sets/{version}/publish",
                                  json={"governance_approval_id": submitted.json()["governance_approval_id"]},
                                  headers=bearer(author))
    assert published.status_code == 200, published.text
    assert [item.id for item in current_runtime().custom_detectors.detectors] == ["custom.case_ref"]

    catalog = (await client.get(f"{BASE}/content-detectors", headers=bearer(author))).json()
    custom = next(item for item in catalog["detectors"] if item["id"] == "custom.case_ref")
    assert custom["used_by"] == ["names-case-ref"] and custom["builtin"] is False
    assert {"pii", "contracts"} <= {item["id"] for item in catalog["categories"]}
    assert next(item for item in catalog["detectors"] if item["id"] == "phone")["used_by"] == []

    # a policy edit on the published version opens a new draft that keeps the detectors
    second = await client.delete(f"{BASE}/policy-sets/{version}/policies/names-case-ref",
                                 headers={**bearer(author), "If-Match": published.json()["digest"]})
    assert second.status_code == 200, second.text
    second_version = second.json()["version"]
    assert second_version["content_detectors"]["detectors"][0]["id"] == "custom.case_ref"

    await client.post(f"{BASE}/policy-sets/{second_version['version']}/retire", headers=bearer(author))
    rollback = await client.post(f"{BASE}/policy-sets/{version}/rollback", headers=bearer(author))
    assert rollback.status_code == 201
    assert rollback.json()["content_detectors"] == published.json()["content_detectors"]
    assert rollback.json()["digest"] == published.json()["digest"]


@pytest.mark.asyncio
async def test_preview_answers_and_never_keeps_the_sample(client, db, caplog):
    admin = await make_user(db, admin=True)
    caplog.set_level(logging.DEBUG)
    sample = "case QX-2026-000042 call +49 30 1234567 mail jane.doe@example.org"
    response = await client.post(f"{BASE}/content-detectors/preview", headers=bearer(admin), json={
        "text": sample, "detectors": {"categories": [CATEGORY], "detectors": [DETECTOR]},
        "mask_style": "last4"})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["counts"] == {"custom.case_ref": 1, "email": 1, "phone": 1}
    assert body["masked_text"] == "case [CASE_REF ******0042 #1] call [PHONE *******4567 #2] mail [EMAIL #3]"
    assert [part.get("detector") for part in body["parts"] if part.get("detector")] == [
        "custom.case_ref", "phone", "email"]
    only_phone = (await client.post(f"{BASE}/content-detectors/preview", headers=bearer(admin), json={
        "text": sample, "mask": ["phone"]})).json()
    assert only_phone["masked_text"] == "case QX-2026-000042 call [PHONE #1] mail jane.doe@example.org"
    invalid = await client.post(f"{BASE}/content-detectors/preview", headers=bearer(admin), json={
        "text": "x", "detectors": {"detectors": [{**DETECTOR, "pattern": "a*"}]}})
    assert invalid.status_code == 422
    for value in ("1234567", "jane.doe@example.org", "QX-2026-000042"):
        assert value not in caplog.text
    audits = [str(row.details) for row in (await db.execute(select(AuditLog))).scalars()]
    assert not any("1234567" in item or "example.org" in item or "QX-2026" in item for item in audits)


@pytest.mark.asyncio
async def test_workspace_scoped_detector_is_accepted_for_an_existing_workspace(client, db):
    admin = await make_user(db, admin=True)
    project_id = (await db.execute(select(Project.id).limit(1))).scalar_one_or_none()
    if project_id is None:
        pytest.skip("no seeded Workspace")
    response = await _put(client, admin, 0, custom_digest(""), {"categories": [CATEGORY], "detectors": [
        {**DETECTOR, "workspace_id": project_id}]})
    assert response.status_code == 200, response.text
    other = Project(name="detector-other-workspace")
    db.add(other)
    await db.commit()
    preview = (await client.post(f"{BASE}/content-detectors/preview", headers=bearer(admin), json={
        "text": "case QX-2026-000042", "workspace_id": other.id})).json()
    assert preview["counts"] == {}  # the detector is scoped to its own Workspace
    unknown = await client.post(f"{BASE}/content-detectors/preview", headers=bearer(admin), json={
        "text": "case QX-2026-000042", "workspace_id": "no-such-workspace"})
    assert unknown.status_code == 404 and unknown.json()["detail"]["code"] == "project_not_found"
    scoped = (await client.post(f"{BASE}/content-detectors/preview", headers=bearer(admin), json={
        "text": "case QX-2026-000042", "workspace_id": project_id})).json()
    assert scoped["counts"] == {"custom.case_ref": 1}


@pytest.mark.asyncio
async def test_a_whole_text_save_keeps_the_detectors(client, db):
    admin = await make_user(db, admin=True)
    draft = await _first_draft(client, admin)
    saved = await client.put(f"{BASE}/policy-sets/{draft['version']}", json={"policies": USES_DETECTOR},
                             headers={**bearer(admin), "If-Match": draft["digest"]})
    assert saved.status_code == 200, saved.text
    assert saved.json()["content_detectors"] == draft["content_detectors"]


@pytest.mark.asyncio
async def test_a_detector_a_policy_names_cannot_be_removed(client, db):
    admin = await make_user(db, admin=True)
    draft = await _first_draft(client, admin)
    saved = await client.put(f"{BASE}/policy-sets/{draft['version']}", json={"policies": USES_DETECTOR},
                             headers={**bearer(admin), "If-Match": draft["digest"]})
    removed = await _put(client, admin, draft["version"], saved.json()["digest"],
                         {"categories": [CATEGORY], "detectors": []})
    assert removed.status_code == 422
    issue = removed.json()["detail"]["issues"][0]
    assert issue["code"] == "detector_in_use" and issue["detector_id"] == "custom.case_ref"
    assert "names-case-ref" in issue["message"]
    edited = await _put(client, admin, draft["version"], saved.json()["digest"],
                        {"categories": [CATEGORY], "detectors": [{**DETECTOR, "label": "Case ref"}]})
    assert edited.status_code == 200, edited.text
