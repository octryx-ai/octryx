"""The classification policy changes only through governed versions (draft → review → publish)."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.models import AuditLog
from app.services.data_classification.policy_matrix import load_classification_policy
from app.services.data_classification.policy_matrix_admin import set_classification_policy
from app.services.governance.approval_rule import APPROVAL_RULE_CONFIG_KEY
from app.services.knowledge.projection.workspace_classification_values import instance_default_for
from app.services.system_config.values import set_system_config_value
from tests.factories import make_project
from tests.policy_engine_support import bearer, make_user

pytestmark = pytest.mark.without_baseline_runtime

ROUTE = "/api/v1/admin/data-classification/policy"
TESTS = "/api/v1/admin/policy-engine/tests"


async def _workspace(db, level: str = "internal") -> str:
    return (await make_project(
        db,
        name=f"ws-{uuid.uuid4().hex[:8]}",
        config={"data_policy": {"classification": level}},
        commit=True,
    )).id


async def _single_admin(db) -> None:
    await set_system_config_value(db, key=APPROVAL_RULE_CONFIG_KEY, value="single_admin")
    await db.commit()


def _draft(**internal) -> dict:
    return {"levels": [{"level": "internal", "rules": internal}], "default_level": "confidential"}


@pytest.mark.asyncio
async def test_a_draft_is_reviewed_by_a_second_admin_and_publishing_writes_the_live_stores(client, db):
    author, reviewer = await make_user(db, admin=True), await make_user(db, admin=True)
    await _workspace(db, "internal")

    saved = await client.put(f"{ROUTE}/draft", json=_draft(reranker_allowed=False), headers=bearer(author))
    assert saved.status_code == 200, saved.text
    draft = saved.json()["draft"]
    assert draft["state"] == "draft" and draft["affected_workspaces"] >= 1
    assert {line["rule"] for line in draft["changes"]} == {"default_level", "reranker_allowed"}
    assert "classification:internal:reranker-forbidden" in draft["policy_diff"]["added"]
    internal = next(item["rules"] for item in draft["levels"] if item["level"] == "internal")
    assert internal["reranker_allowed"] is False
    assert (await load_classification_policy(db)).rules_for("internal").reranker_allowed is True, "nothing live yet"

    submitted = await client.post(f"{ROUTE}/draft/submit", json={"note": "tighten"}, headers=bearer(author))
    assert submitted.status_code == 200, submitted.text
    version = submitted.json()["draft"]["version"]
    assert submitted.json()["draft"]["state"] == "in_review"
    assert submitted.json()["draft"]["review"]["can_approve"] is False, "four-eyes: not the author"
    assert (await client.put(f"{ROUTE}/draft", json=_draft(), headers=bearer(author))).status_code == 409

    own = await client.post(f"{ROUTE}/versions/{version}/approve", headers=bearer(author))
    assert own.status_code == 403 and own.json()["detail"]["code"] == "classification_self_approval_not_allowed"

    published = await client.post(f"{ROUTE}/versions/{version}/approve", headers=bearer(reviewer))
    assert published.status_code == 200, published.text
    body = published.json()
    assert body["draft"] is None and body["published_version"] == version
    assert body["versions"][0]["approved_by"] and body["versions"][0]["state"] == "published"
    db.expire_all()
    assert (await load_classification_policy(db)).rules_for("internal").reranker_allowed is False
    assert (await instance_default_for(db))[0] == "confidential"
    audit = (await db.execute(select(AuditLog).where(AuditLog.action == "admin.data_classification.published"))).scalar_one()
    assert audit.details["approval_mode"] == "four_eyes" and audit.details["approved_by"] == reviewer


@pytest.mark.asyncio
async def test_under_single_admin_the_author_approves_their_own_change(client, db):
    admin = await make_user(db, admin=True)
    await _single_admin(db)
    await client.put(f"{ROUTE}/draft", json=_draft(device_runs_allowed=False), headers=bearer(admin))
    submitted = (await client.post(f"{ROUTE}/draft/submit", json={}, headers=bearer(admin))).json()
    assert submitted["draft"]["review"]["can_approve"] is True and submitted["self_approval"] is True

    published = await client.post(f"{ROUTE}/versions/{submitted['draft']['version']}/approve", headers=bearer(admin))
    assert published.status_code == 200, published.text
    db.expire_all()
    assert (await load_classification_policy(db)).rules_for("internal").device_runs_allowed is False
    assert (await db.execute(select(AuditLog).where(AuditLog.action == "governance.four_eyes.self_approval"))).first()


@pytest.mark.asyncio
async def test_a_rejected_review_returns_to_draft_and_a_discarded_draft_changes_nothing(client, db):
    author, reviewer = await make_user(db, admin=True), await make_user(db, admin=True)
    await client.put(f"{ROUTE}/draft", json=_draft(seat_allowed=False), headers=bearer(author))
    version = (await client.post(f"{ROUTE}/draft/submit", json={}, headers=bearer(author))).json()["draft"]["version"]

    rejected = await client.post(f"{ROUTE}/versions/{version}/reject", json={"comment": "too strict"},
                                 headers=bearer(reviewer))
    assert rejected.status_code == 200 and rejected.json()["draft"]["state"] == "draft"
    assert (await client.put(f"{ROUTE}/draft", json=_draft(), headers=bearer(author))).status_code == 200

    discarded = await client.delete(f"{ROUTE}/draft", headers=bearer(author))
    assert discarded.status_code == 200 and discarded.json()["draft"] is None
    assert (await load_classification_policy(db)).rules_for("internal").seat_allowed is True


@pytest.mark.asyncio
async def test_a_failing_saved_test_case_blocks_the_submit(client, db):
    admin = await make_user(db, admin=True)
    workspace = await _workspace(db, "internal")
    case = {"name": "reranker for internal", "expected": "allow",
            "request": {"workspace_id": workspace, "action": "use_reranker", "resource": {"data_policy_class": "internal"}}}
    assert (await client.post(TESTS, json=case, headers=bearer(admin))).status_code == 201

    await client.put(f"{ROUTE}/draft", json=_draft(reranker_allowed=False), headers=bearer(admin))
    refused = await client.post(f"{ROUTE}/draft/submit", json={}, headers=bearer(admin))
    assert refused.status_code == 409 and refused.json()["detail"]["code"] == "classification_draft_tests_failed"
    assert refused.json()["detail"]["test_report"]["failed"] == 1
    listing = (await client.get(f"{ROUTE}/versions", headers=bearer(admin))).json()
    assert listing["draft"]["state"] == "draft" and listing["draft"]["test_report"]["ok"] is False
    assert (await load_classification_policy(db)).rules_for("internal").reranker_allowed is True, "live unaffected"


@pytest.mark.asyncio
async def test_the_model_list_is_not_edited_through_a_draft_and_there_is_no_direct_write(client, db):
    admin = await make_user(db, admin=True)
    await set_classification_policy(db, levels=[{"level": "internal", "rules": {"allowed_model_aliases": ["kept"]}}],
                                    actor_id=admin)
    await db.commit()

    published = (await client.get(ROUTE, headers=bearer(admin))).json()
    derived = next(item["rules"] for item in published["levels"] if item["level"] == "internal")["allowed_model_aliases"]
    saved = await client.put(f"{ROUTE}/draft", json=_draft(allowed_model_aliases=["other"]), headers=bearer(admin))
    internal = next(item["rules"] for item in saved.json()["draft"]["levels"] if item["level"] == "internal")
    # The list is derived from the Model catalog's clearance; neither a stored value nor a
    # draft changes it.
    assert internal["allowed_model_aliases"] == derived and derived != ["kept"] and derived != ["other"]
    assert (await client.put(ROUTE, json={"levels": []}, headers=bearer(admin))).status_code == 405
    assert (await client.put("/api/v1/admin/data-classification/default", json={"classification": "public"},
                             headers=bearer(admin))).status_code == 405


@pytest.mark.asyncio
async def test_drafts_are_for_platform_admins_and_validated_with_a_code(client, db):
    member = await make_user(db, admin=False)
    admin = await make_user(db, admin=True)
    assert (await client.put(f"{ROUTE}/draft", json=_draft(), headers=bearer(member))).status_code == 403
    assert (await client.get(f"{ROUTE}/versions", headers=bearer(member))).status_code == 403
    bad = await client.put(f"{ROUTE}/draft", json={"levels": [{"level": "top", "rules": {}}]}, headers=bearer(admin))
    assert bad.status_code == 422 and bad.json()["detail"] == {"code": "classification_policy_level_unknown",
                                                              "path": "levels[0].level"}
    unknown_default = await client.put(f"{ROUTE}/draft", json={"levels": [], "default_level": "top"},
                                       headers=bearer(admin))
    assert unknown_default.status_code == 422
    assert (await client.get(f"{ROUTE}/versions", headers=bearer(admin))).json()["draft"] is None
