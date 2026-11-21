"""The Model Policy registry: API contract, admission refusal and the governed four-eyes publication.

An alias no gateway admits is an explicit ``needs_configuration`` refusal at submit. Publication needs a
governance approval decided by someone else, unless the platform approval rule allows self-approval.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.models import Approval, AuditLog
from app.services.governance import four_eyes
from app.services.governance.approval_rule import set_approval_rule
from app.services.governance.four_eyes import SELF_APPROVAL_AUDIT_ACTION
from app.services.model_policy import policies
from app.services.model_policy.entries import AliasAdmissionState, ModelPolicyAdmission
from app.services.model_policy.errors import RegistryRefusalError
from tests.agent_definition_revision_fixtures import auth_headers
from tests.model_policy_support import decide_approval, four_eyes_settings, seed_workspace

ENTRIES = [
    {"alias": "reasoning-large", "required_capabilities": ["tools", "reasoning"]},
    {"alias": "fast-small", "required_capabilities": ["tools"]},
]


@pytest.fixture(autouse=True)
def _default_four_eyes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(four_eyes, "get_settings", lambda: four_eyes_settings(dev_self_approval=False))


@pytest.fixture
def admitted(monkeypatch: pytest.MonkeyPatch) -> None:
    async def every_alias_admitted(_db, _workspace_id, revision):
        return ModelPolicyAdmission(tuple(AliasAdmissionState(entry["alias"], "admitted") for entry in
                                          revision.entries_json))

    monkeypatch.setattr(policies, "policy_admission", every_alias_admitted)


@pytest.mark.asyncio
async def test_model_policy_with_unadmitted_alias_is_needs_configuration(client, db):
    seeded = await seed_workspace(db)
    created = await client.post(
        "/api/v1/model-policies",
        json={"workspace_id": seeded.project.id, "name": "default-models", "entries": ENTRIES},
        headers=auth_headers(seeded.author),
    )
    assert created.status_code == 201, created.text
    revision = created.json()["revision"]
    assert [entry["alias"] for entry in revision["entries"]] == ["reasoning-large", "fast-small"]

    policy_id = created.json()["policy"]["id"]
    refused = await client.post(
        f"/api/v1/model-policies/{policy_id}/revisions/1/submit", headers=auth_headers(seeded.author)
    )
    assert refused.status_code == 409
    detail = refused.json()["detail"]
    assert detail["code"] == "needs_configuration"
    assert [entry["reason"] for entry in detail["admission"]["entries"]] == [
        "no_gateway_provider",
        "no_gateway_provider",
    ]

    malformed = await client.post(
        "/api/v1/model-policies",
        json={"workspace_id": seeded.project.id, "name": "empty", "entries": []},
        headers=auth_headers(seeded.author),
    )
    assert malformed.status_code == 422
    assert malformed.json()["detail"] == {"code": "model_policy_entries_invalid", "reason": "entries_empty"}


@pytest.mark.asyncio
async def test_a_member_reads_but_cannot_author_and_a_stranger_gets_not_found(client, db):
    seeded = await seed_workspace(db)
    listed = await client.get(
        f"/api/v1/model-policies?workspace_id={seeded.project.id}", headers=auth_headers(seeded.member)
    )
    assert listed.status_code == 200, listed.text
    refused = await client.post(
        "/api/v1/model-policies",
        json={"workspace_id": seeded.project.id, "name": "member-models", "entries": ENTRIES},
        headers=auth_headers(seeded.member),
    )
    assert refused.status_code == 403


async def _policy_in_review(db):
    seeded = await seed_workspace(db)
    policy, revision = await policies.create_policy(
        db, workspace_id=seeded.project.id, name="triage-models", entries=ENTRIES, user=seeded.author
    )
    await policies.submit_policy_revision(db, policy=policy, revision=revision, user=seeded.author)
    return seeded, policy, revision


@pytest.mark.asyncio
async def test_publication_needs_a_distinct_approver(db, admitted):
    seeded, policy, revision = await _policy_in_review(db)
    with pytest.raises(RegistryRefusalError):
        await policies.publish_policy_revision(db, policy=policy, revision=revision, approval_id=None,
                                               user=seeded.author, self_approve=True)
    assert (await db.get(Approval, revision.approval_id)).status == "pending"

    await decide_approval(db, revision.approval_id, seeded.reviewer)
    gate = await policies.publish_policy_revision(
        db, policy=policy, revision=revision, approval_id=revision.approval_id, user=seeded.author
    )
    assert (revision.state, gate["status"], gate["approval_mode"]) == ("published", "approved", "four_eyes")


@pytest.mark.asyncio
async def test_self_approval_only_under_the_single_admin_rule(db, admitted):
    seeded, policy, revision = await _policy_in_review(db)
    await set_approval_rule(db, rule="single_admin", actor_id=seeded.author.id)
    gate = await policies.publish_policy_revision(
        db, policy=policy, revision=revision, approval_id=None, user=seeded.author, self_approve=True
    )
    assert (revision.state, gate["status"], gate["approval_mode"]) == ("published", "approved_self_approval", "self")
    audits = (await db.execute(select(AuditLog).where(AuditLog.action == SELF_APPROVAL_AUDIT_ACTION))).scalars()
    assert [row.resource_type for row in audits] == ["model_policy_revision"]
