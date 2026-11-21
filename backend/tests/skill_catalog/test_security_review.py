"""Security review in the lifecycle — findings on every save, acknowledgement, blocking findings."""

from __future__ import annotations

import pytest

from tests.policy_engine_support import bearer, make_user
from tests.skill_catalog.fake_git import COMMUNITY, OFFICIAL
from tests.skill_catalog.support import BASE, category

SCRIPT_ID = "script:scripts/validate-chart.sh"
HELM_PATH = "plugins/kubernetes-operations/skills/helm-chart-scaffolding"


async def _review_round(client, author, reviewer, skill_id, version):
    approval_id = (await client.post(f"{BASE}/skills/{skill_id}/versions/{version}/submit",
                                     headers=bearer(author))).json()["governance_approval_id"]
    await client.post(f"/api/v1/approvals/{approval_id}/approve", json={"reason": "ok"}, headers=bearer(reviewer))
    return await client.post(f"{BASE}/skills/{skill_id}/versions/{version}/publish",
                             json={"governance_approval_id": approval_id}, headers=bearer(author))


async def _withdraw_and_reopen(client, author, skill_id, version):
    await client.post(f"{BASE}/skills/{skill_id}/versions/{version}/retire", headers=bearer(author))
    return (await client.post(f"{BASE}/skills/{skill_id}/versions/{version}/rollback", headers=bearer(author))).json()


async def _save(client, author, skill_id, version, etag, **payload):
    response = await client.put(f"{BASE}/skills/{skill_id}/versions/{version}", json=payload,
                                headers={**bearer(author), "If-Match": etag})
    assert response.status_code == 200, response.text
    return response.json()


@pytest.mark.asyncio
async def test_a_withheld_script_needs_an_acknowledgement_to_publish(client, db, fake_git):
    author, reviewer = await make_user(db, admin=True), await make_user(db, admin=True)
    helm = (await category(db, "kubernetes.helm")).id
    commit = fake_git.refs[COMMUNITY]["main"]
    imported = await client.post(f"{BASE}/import/git", headers=bearer(author), json={
        "url": COMMUNITY, "ref": "main", "commit": commit, "trust": "community",
        "items": [{"path": HELM_PATH, "category_id": helm}]})
    skill_id = imported.json()["imported"][0]["skill_id"]
    draft = (await client.get(f"{BASE}/skills/{skill_id}/versions/1", headers=bearer(author))).json()
    findings = {item["id"]: item for item in draft["security_report"]["findings"]}
    assert findings[SCRIPT_ID]["effect"] == "withheld" and draft["security_report"]["summary"]["high"] == 1

    refused = await _review_round(client, author, reviewer, skill_id, 1)
    assert refused.json()["detail"] == {"code": "skill_findings_unacknowledged", "findings": [SCRIPT_ID]}

    reopened = await _withdraw_and_reopen(client, author, skill_id, 1)
    saved = await _save(client, author, skill_id, 2, reopened["digest"],
                        acknowledged_findings=[SCRIPT_ID, "secret:nowhere:1", "network:SKILL.md:1"])
    assert saved["acknowledged_findings"] == [SCRIPT_ID]  # only existing findings that take an acknowledgement
    allowed = await _save(client, author, skill_id, 2, saved["digest"], scripts_allowed=True,
                          scripts_reason="Chart linting is part of the team's review.")
    script = next(item for item in allowed["security_report"]["findings"] if item["id"] == SCRIPT_ID)
    assert script["effect"] == "delivered (allowed)" and allowed["scripts_allowed_by"] == author
    assert (await _review_round(client, author, reviewer, skill_id, 2)).status_code == 200


@pytest.mark.asyncio
async def test_secrets_and_a_missing_licence_block_publishing_even_when_acknowledged(client, db):
    author, reviewer = await make_user(db, admin=True), await make_user(db, admin=True)
    docs = (await category(db, "engineering.documentation")).id
    created = await client.post(f"{BASE}/skills", headers=bearer(author), json={
        "name": "leaky-skill", "category_id": docs, "body": "\n# Leaky\n",
        "frontmatter": {"description": "d"}, "files": {"references/env.md": ("AKIAAB" + "CDEFGHIJKLMNOP\n")}})
    skill_id, etag = created.json()["skill_id"], created.json()["digest"]
    secret_id = "secret:references/env.md:1"
    saved = await _save(client, author, skill_id, 1, etag, acknowledged_findings=[secret_id], licence_spdx="")
    assert {item["id"] for item in saved["security_report"]["findings"] if item["blocks"]} == {secret_id,
                                                                                              "licence_missing"}
    assert saved["acknowledged_findings"] == []
    refused = await _review_round(client, author, reviewer, skill_id, 1)
    assert refused.json()["detail"]["code"] == "skill_findings_blocking"
    assert set(refused.json()["detail"]["findings"]) == {secret_id, "licence_missing"}
    reopened = await _withdraw_and_reopen(client, author, skill_id, 1)
    cleaned = await _save(client, author, skill_id, 2, reopened["digest"], files={"references/env.md": None},
                          licence_spdx="Internal")
    assert cleaned["security_report"]["summary"]["high"] == 0
    assert (await _review_round(client, author, reviewer, skill_id, 2)).status_code == 200


@pytest.mark.asyncio
async def test_the_detail_lists_findings_new_against_the_published_version(client, db):
    author, reviewer = await make_user(db, admin=True), await make_user(db, admin=True)
    docs = (await category(db, "engineering.documentation")).id
    created = await client.post(f"{BASE}/skills", headers=bearer(author), json={
        "name": "status-skill", "category_id": docs, "frontmatter": {"description": "d"},
        "body": "\n# Status\n\nNodes: !`kubectl get nodes`\n"})
    skill_id = created.json()["skill_id"]
    first = next(item["id"] for item in created.json()["security_report"]["findings"])
    acked = await _save(client, author, skill_id, 1, created.json()["digest"], acknowledged_findings=[first])
    assert acked["acknowledged_findings"] == [first]
    assert (await _review_round(client, author, reviewer, skill_id, 1)).status_code == 200
    draft = (await client.post(f"{BASE}/skills/{skill_id}/edit", headers=bearer(author))).json()
    await _save(client, author, skill_id, 2, draft["digest"],
                body="\n# Status\n\nNodes: !`kubectl get nodes`\nPods: !`kubectl get pods`\n")
    detail = (await client.get(f"{BASE}/skills/{skill_id}", headers=bearer(author))).json()
    assert [item["id"] for item in detail["new_findings"]] == [first[:-1] + str(int(first[-1]) + 1)]


@pytest.mark.asyncio
async def test_the_marketplace_inspect_previews_the_mcp_findings(client, db, fake_git):
    author = await make_user(db, admin=True)
    body = (await client.post(f"{BASE}/import/inspect", headers=bearer(author),
                              json={"url": OFFICIAL, "ref": "main", "marketplace_plugin": "terraform"})).json()
    assert body["mcp_servers"][0]["security"] == {"high": 1, "medium": 2, "info": 1}
