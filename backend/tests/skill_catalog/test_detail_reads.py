"""UI reads: which Workspaces receive a skill, and the delivery preview of a version."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.models import Project
from app.services.skill_catalog.bundle import BundleFile
from tests.policy_engine_support import bearer, make_user
from tests.skill_catalog.support import BASE, category, published_skill

SKILL = """---
name: style-guide
description: Write HCL in the house style.
allowed-tools: Bash(terraform apply *)
model: some-model
---

# Style guide
"""


@pytest.mark.asyncio
async def test_reach_lists_assigned_workspaces_and_the_preview_strips_and_withholds(client, db, auth_user):
    terraform = (await category(db, "iac.terraform")).id
    skill, version = await published_skill(db, terraform, "style-guide", approver_id=auth_user.id, files=[
        BundleFile("SKILL.md", SKILL), BundleFile("scripts/fmt.sh", "#!/bin/sh\nterraform fmt\n", True),
        BundleFile("LICENSE", "MIT License\n")], licence_spdx="MIT")
    skill_id = skill.id
    await db.commit()
    project_id = (await db.execute(select(Project.id).where(Project.name == "acme-orders"))).scalar_one()
    view = (await client.get(f"{BASE}/workspaces/{project_id}/skills", headers=bearer(auth_user.id))).json()
    saved = await client.put(f"{BASE}/workspaces/{project_id}/skills",
                             headers={**bearer(auth_user.id), "If-Match": view["digest"]},
                             json={**view["policy"], "mode": "selected_only", "category_keys": ["kubernetes"]})
    assert saved.status_code == 200, saved.text

    reach = (await client.get(f"{BASE}/skills/{skill_id}/workspaces", headers=bearer(auth_user.id))).json()
    names = {row["name"]: row for row in reach["workspaces"]}
    assert "acme-orders" not in names and names  # only Kubernetes is assigned there; other Workspaces get all
    first = next(iter(names.values()))
    assert first["surfaces"]["octryx_claude"]["delivered"] is True
    categories = (await client.get(f"{BASE}/categories", headers=bearer(auth_user.id))).json()
    assert categories["assigned_in"] == {"kubernetes": 1}
    assert first["surfaces"]["octryx_claude"]["readiness"]["state"] in {"ready", "restricted"}
    rows = (await client.get(f"{BASE}/skills", headers=bearer(auth_user.id))).json()["items"]
    assert next(row for row in rows if row["id"] == skill_id)["workspaces"] == len(names)

    preview = (await client.get(f"{BASE}/skills/{skill_id}/versions/{version.version}/delivery",
                                headers=bearer(auth_user.id))).json()
    assert preview["stripped_keys"] == ["allowed-tools", "model"] and preview["scripts_withheld"] == ["scripts/fmt.sh"]
    assert "allowed-tools" not in preview["skill_md"] and "model:" not in preview["skill_md"]
    assert [item["path"] for item in preview["files"]] == ["LICENSE", "SKILL.md"]
    assert preview["command"] == "/octryx:style-guide"

    member = await make_user(db, admin=False)
    for path in (f"/skills/{skill_id}/workspaces", f"/skills/{skill_id}/versions/1/delivery"):
        assert (await client.get(f"{BASE}{path}", headers=bearer(member))).status_code == 403
