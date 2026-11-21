"""Categories (two-level tree, stable keys, archive rules, counts) and free tags."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.models import Skill, SkillCategory, SystemConfig
from app.services.skill_catalog.categories import STARTER_MARKER, STARTER_TREE, ensure_starter_categories
from tests.policy_engine_support import bearer, make_user
from tests.skill_catalog.support import category, draft_skill, published_skill

# Two published chat-only skills as a fixture.
pytestmark = pytest.mark.usefixtures("chat_skills")

BASE = "/api/v1/admin/skill-catalog"


async def _create(client, admin, **payload):
    response = await client.post(f"{BASE}/categories", json=payload, headers=bearer(admin))
    return response


def _flat(tree: list[dict]) -> dict[str, dict]:
    rows = {}
    for root in tree:
        rows[root["key"]] = root
        for child in root["children"]:
            rows[child["key"]] = child
    return rows


@pytest.mark.asyncio
async def test_endpoints_are_platform_admin_only(client, db):
    member = await make_user(db, admin=False)
    for method, path in [("get", "/categories"), ("post", "/categories"), ("patch", "/categories/x"),
                         ("post", "/categories/x/archive"), ("put", "/skills/x/tags")]:
        kwargs = {"json": {"key": "a", "label": "A", "tags": []}} if method != "get" else {}
        response = await getattr(client, method)(f"{BASE}{path}", headers=bearer(member), **kwargs)
        assert response.status_code == 403, path


@pytest.mark.asyncio
async def test_the_starter_tree_is_seeded_once_with_eighteen_categories(client, db):
    admin = await make_user(db, admin=True)
    rows = _flat((await client.get(f"{BASE}/categories", headers=bearer(admin))).json()["categories"])
    starter = {key for key, _label, _children in STARTER_TREE} | {
        f"{key}.{child}" for key, _label, children in STARTER_TREE for child, _ in children}
    assert len(starter) == 18 and starter <= set(rows)
    assert rows["iac.terraform"]["parent_id"] == rows["iac"]["id"]
    # The two fixture skills live in "diagnosis" and are counted.
    assert rows["diagnosis"]["skills"] == 2 and rows["diagnosis"]["total"] == 2
    assert await db.get(SystemConfig, STARTER_MARKER) is not None
    assert await ensure_starter_categories(db) == 0


@pytest.mark.asyncio
async def test_a_second_seed_does_not_recreate_categories_an_admin_archived(db):
    marker = await db.get(SystemConfig, STARTER_MARKER)
    await db.delete(marker)
    packer = (await db.execute(select(SkillCategory).where(SkillCategory.key == "iac.packer"))).scalar_one()
    await db.delete(packer)
    await db.flush()
    assert await ensure_starter_categories(db) == 1  # only the missing child is recreated, nothing duplicated
    keys = list((await db.execute(select(SkillCategory.key))).scalars())
    assert len(keys) == len(set(keys))


@pytest.mark.asyncio
async def test_keys_are_stable_and_the_tree_has_two_levels(client, db):
    admin = await make_user(db, admin=True)
    top = await _create(client, admin, key="data", label="Data")
    assert top.status_code == 201, top.text
    top_id = top.json()["id"]
    child = await _create(client, admin, key="pipelines", label="Pipelines", parent_id=top_id)
    assert child.status_code == 201 and child.json()["key"] == "data.pipelines"
    full = await _create(client, admin, key="data.lakes", label="Lakes", parent_id=top_id)
    assert full.json()["key"] == "data.lakes"
    for payload, code in [
        ({"key": "deep", "label": "Deep", "parent_id": child.json()["id"]}, "skill_category_too_deep"),
        ({"key": "Bad Key", "label": "x"}, "skill_category_key_invalid"),
        ({"key": "a.b", "label": "x"}, "skill_category_key_invalid"),
        ({"key": "other.x", "label": "x", "parent_id": top_id}, "skill_category_key_invalid"),
        ({"key": "data.x.y", "label": "x", "parent_id": top_id}, "skill_category_key_invalid"),
        ({"key": "data", "label": "dup"}, "skill_category_key_exists"),
        ({"key": "x", "label": "x", "parent_id": "missing"}, "skill_category_parent_not_found"),
        ({"key": "y", "label": "  "}, "skill_category_label_required"),
    ]:
        response = await _create(client, admin, **payload)
        assert response.json()["detail"]["code"] == code, (payload, response.text)
    renamed = await client.patch(f"{BASE}/categories/{top_id}", json={"label": "Data platform", "sort_order": 3},
                                 headers=bearer(admin))
    assert renamed.json()["label"] == "Data platform" and renamed.json()["key"] == "data"
    for payload, code in [({"key": "data2"}, "skill_category_key_immutable"),
                          ({"parent_id": child.json()["id"]}, "skill_category_parent_immutable")]:
        response = await client.patch(f"{BASE}/categories/{top_id}", json=payload, headers=bearer(admin))
        assert response.status_code == 422 and response.json()["detail"]["code"] == code
    assert (await client.patch(f"{BASE}/categories/{top_id}", json={"key": "data"}, headers=bearer(admin))
            ).status_code == 200


@pytest.mark.asyncio
async def test_a_category_with_skills_or_children_cannot_be_archived(client, db):
    admin = await make_user(db, admin=True)
    diagnosis = (await db.execute(select(SkillCategory).where(SkillCategory.key == "diagnosis"))).scalar_one()
    busy = await client.post(f"{BASE}/categories/{diagnosis.id}/archive", headers=bearer(admin))
    assert busy.status_code == 409
    assert busy.json()["detail"] == {"code": "skill_category_not_empty", "skills": 2, "children": 0}
    iac = (await db.execute(select(SkillCategory).where(SkillCategory.key == "iac"))).scalar_one()
    parent = await client.post(f"{BASE}/categories/{iac.id}/archive", headers=bearer(admin))
    assert parent.json()["detail"]["children"] == 2
    packer = (await db.execute(select(SkillCategory).where(SkillCategory.key == "iac.packer"))).scalar_one()
    archived = await client.post(f"{BASE}/categories/{packer.id}/archive", headers=bearer(admin))
    assert archived.status_code == 200 and archived.json()["archived"] is True
    blocked = await _create(client, admin, key="x", label="x", parent_id=packer.id)
    assert blocked.json()["detail"]["code"] == "skill_category_too_deep"
    terraform = (await db.execute(select(SkillCategory).where(SkillCategory.key == "iac.terraform"))).scalar_one()
    assert (await client.post(f"{BASE}/categories/{terraform.id}/archive", headers=bearer(admin))).status_code == 200
    assert (await client.post(f"{BASE}/categories/{iac.id}/archive", headers=bearer(admin))).status_code == 200
    child_restore = await client.post(f"{BASE}/categories/{packer.id}/restore", headers=bearer(admin))
    assert child_restore.json()["detail"]["code"] == "skill_category_archived"
    assert (await client.post(f"{BASE}/categories/{iac.id}/restore", headers=bearer(admin))).json()["archived"] is False
    assert (await client.post(f"{BASE}/categories/{packer.id}/restore", headers=bearer(admin))).status_code == 200


@pytest.mark.asyncio
async def test_tags_are_free_lower_case_identity_metadata(client, db):
    admin = await make_user(db, admin=True)
    skill = (await db.execute(select(Skill).where(Skill.name == "cluster-health"))).scalar_one()
    saved = await client.put(f"{BASE}/skills/{skill.id}/tags", json={"tags": ["K8s", "health", "k8s"]},
                             headers=bearer(admin))
    assert saved.json() == {"skill_id": skill.id, "tags": ["health", "k8s"]}
    bad = await client.put(f"{BASE}/skills/{skill.id}/tags", json={"tags": ["has space"]}, headers=bearer(admin))
    assert bad.status_code == 422 and bad.json()["detail"]["tags"] == ["has space"]
    many = await client.put(f"{BASE}/skills/{skill.id}/tags", json={"tags": [f"t{i}" for i in range(21)]},
                            headers=bearer(admin))
    assert many.json()["detail"]["code"] == "skill_tags_too_many"
    missing = await client.put(f"{BASE}/skills/nope/tags", json={"tags": []}, headers=bearer(admin))
    assert missing.status_code == 404
    cloud = (await client.get(f"{BASE}/categories", headers=bearer(admin))).json()["tags"]
    assert {"tag": "k8s", "skills": 1} in cloud


@pytest.mark.asyncio
async def test_counts_cover_published_versions_and_roll_up_to_the_parent(client, db):
    admin = await make_user(db, admin=True)
    terraform = await category(db, "iac.terraform")
    iac = await category(db, "iac")
    await published_skill(db, terraform.id, approver_id=admin)
    await published_skill(db, iac.id, approver_id=admin)
    await draft_skill(db, terraform.id)  # drafts are not counted
    await db.commit()
    rows = _flat((await client.get(f"{BASE}/categories", headers=bearer(admin))).json()["categories"])
    assert rows["iac.terraform"]["skills"] == 1 and rows["iac.terraform"]["total"] == 1
    assert rows["iac"]["skills"] == 1 and rows["iac"]["total"] == 2
