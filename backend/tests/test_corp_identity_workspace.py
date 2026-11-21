"""A Workspace's Corporate Identity and the profile's Spec Studio locks.

The CI stays one feature: a Workspace names one of the existing profiles (empty: the installation default), a
profile locks token paths for the Spec Studio, and disk hygiene keeps every profile a Workspace uses.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.models import AuditLog
from app.services.corp_identity.registry import CORP_IDENTITY_DEFAULT_PROFILE_KEY, save_registry
from app.services.corp_identity.workspace import assigned_profile_ids, effective_profile
from app.services.system_config import set_system_config_value


async def _profiles(db, *ids: str) -> None:
    await save_registry(db, [{"id": pid, "name": f"Brand {pid}", "profile_root": f"/nowhere/{pid}"} for pid in ids])
    await set_system_config_value(db, key=CORP_IDENTITY_DEFAULT_PROFILE_KEY, value=ids[0], description="Default.")
    await db.commit()


async def _workspace(client, auth_headers, name: str) -> str:
    created = await client.post("/api/v1/projects", headers=auth_headers, json={"name": name})
    assert created.status_code in (200, 201), created.text
    return created.json()["id"]


def _address(project_id: str) -> str:
    return f"/admin/chat/api/panel/workspaces/{project_id}/corp-identity"


@pytest.mark.asyncio
async def test_a_workspace_uses_the_installation_default_until_it_names_its_own_profile(client, auth_headers, db):
    await _profiles(db, "house", "product")
    project_id = await _workspace(client, auth_headers, "Coffee")
    view = (await client.get(_address(project_id), headers=auth_headers)).json()
    assert view["chosen"] == "" and view["effective"]["profile_id"] == "house"
    assert view["effective"]["source"] == "installation"

    saved = await client.put(_address(project_id), headers=auth_headers, json={"profile_id": "product"})
    assert saved.status_code == 200, saved.text
    assert saved.json()["effective"] == {"profile_id": "product", "profile_name": "Brand product",
                                         "source": "workspace", "locks": [], "updated_at": ""}
    audits = (await db.execute(select(AuditLog).where(AuditLog.action == "admin.project_config.updated"))).scalars()
    assert any("corp_identity_profile_id" in str(audit.details) for audit in audits)
    assert await assigned_profile_ids(db) == {"house", "product"}

    # Back to the installation default.
    cleared = await client.put(_address(project_id), headers=auth_headers, json={"profile_id": ""})
    assert cleared.json()["effective"]["profile_id"] == "house"


@pytest.mark.asyncio
async def test_an_unknown_profile_is_refused_and_a_deleted_one_falls_back_to_the_default(client, auth_headers, db):
    await _profiles(db, "house", "product")
    project_id = await _workspace(client, auth_headers, "Tea")
    unknown = await client.put(_address(project_id), headers=auth_headers, json={"profile_id": "nope"})
    assert unknown.status_code == 404 and "corp_identity_profile_unknown" in unknown.text
    malformed = await client.put(_address(project_id), headers=auth_headers, json={"profile_id": "../etc"})
    assert malformed.status_code == 400
    await client.put(_address(project_id), headers=auth_headers, json={"profile_id": "product"})
    await _profiles(db, "house")  # "product" deleted: a spec must still get a corporate direction
    assert (await effective_profile(db, project_id))["profile_id"] == "house"


@pytest.mark.asyncio
async def test_locked_token_paths_are_stored_on_the_profile_and_unknown_paths_refused(client, auth_headers, db):
    await _profiles(db, "house")
    address = "/admin/chat/api/panel/corp-identities/house/studio-locks"
    refused = await client.put(address, headers=auth_headers, json={"paths": ["light.accent", "light.sparkle"]})
    assert refused.status_code == 400 and "light.sparkle" in refused.text
    saved = await client.put(address, headers=auth_headers, json={"paths": ["light.accent", "fonts.head",
                                                                            "light.accent"]})
    assert saved.json()["studio_locks"] == ["fonts.head", "light.accent"]
    assert (await effective_profile(db, None))["locks"] == ["fonts.head", "light.accent"]
    missing = await client.put("/admin/chat/api/panel/corp-identities/gone/studio-locks", headers=auth_headers,
                               json={"paths": []})
    assert missing.status_code == 404


@pytest.mark.asyncio
async def test_disk_hygiene_keeps_every_profile_a_workspace_uses(client, auth_headers, db, tmp_path, monkeypatch):
    from app.services.corp_identity import profile_cleanup

    await _profiles(db, "house", "product", "old")
    project_id = await _workspace(client, auth_headers, "Juice")
    await client.put(_address(project_id), headers=auth_headers, json={"profile_id": "product"})
    kept: dict = {}

    async def hygiene(_db, **kwargs):
        kept["hygiene"] = kwargs["excluded_corp_identity_profile_ids"]

    async def prune(_db, **kwargs):
        kept["prune"] = kwargs

    monkeypatch.setattr("app.services.disk_hygiene.run_backend_disk_hygiene", hygiene)
    monkeypatch.setattr(profile_cleanup, "_prune_unreferenced_corp_identity_roots", prune)
    await profile_cleanup._run_corp_identity_cleanup(db, active_profile_id="old", corp_identity_root=tmp_path)
    assert kept["hygiene"] == {"old", "house", "product"} and "prune" in kept
