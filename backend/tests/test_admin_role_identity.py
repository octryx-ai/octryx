"""Identity provider mappings are RBAC-gated and validated, and identity groups are created, assigned and delete-guarded."""

import pytest

from app.models import IdentityGroup, IdentityProvider
from app.services.admin.governance.admin_identity_group_service import create_group, delete_group, list_groups
from app.services.admin.governance.admin_role_service import create_role
from app.services.admin.governance.admin_user_service import create_user, update_user
from tests.admin_role_management_support import _auth_headers_for


@pytest.mark.asyncio
async def test_admin_panel_identity_provider_mapping_is_rbac_gated_and_validated(client, db):
    mapper_role = await create_role(
        db,
        payload={
            "name": "identity-mapper",
            "description": "Manages identity provider mappings",
            "permissions": [
                {"resource": "identity_providers", "action": "read"},
                {"resource": "identity_providers", "action": "write"},
                {"resource": "auth", "action": "login"},
            ],
        },
    )
    await create_user(
        db,
        payload={
            "username": "identity_mapper",
            "email": "identity-mapper@example.com",
            "password": "password123",
            "roles": [mapper_role["name"]],
        },
    )
    engineering_group = IdentityGroup(name="engineering", description="Engineering", is_active=True)
    db.add(engineering_group)
    provider = IdentityProvider(
        name="Enterprise OIDC",
        provider_type="oidc",
        issuer_url="https://issuer.example.com",
        client_id="client-123",
        is_active=True,
    )
    db.add(provider)
    await db.commit()
    headers = await _auth_headers_for(client, "identity_mapper")

    listed = await client.get("/admin/chat/api/panel/identity-providers", headers=headers)
    assert listed.status_code == 200, listed.text
    assert any(item["id"] == provider.id for item in listed.json())

    updated = await client.put(
        f"/admin/chat/api/panel/identity-providers/{provider.id}",
        json={
            "name": provider.name,
            "provider_type": "oidc",
            "issuer_url": provider.issuer_url,
            "client_id": provider.client_id,
            "group_role_mappings": {"external-admins": ["admin"]},
            "group_group_mappings": {"external-admins": [engineering_group.id]},
            "default_roles": ["viewer"],
            "default_group_ids": [engineering_group.id],
        },
        headers=headers,
    )
    assert updated.status_code == 200, updated.text
    payload = updated.json()
    assert payload["groupRoleMappings"] == {"external-admins": ["admin"]}
    assert payload["groupGroupMappings"] == {"external-admins": [engineering_group.id]}
    assert payload["defaultRoles"] == ["viewer"]
    assert payload["defaultGroupIds"] == [engineering_group.id]

    invalid = await client.put(
        f"/admin/chat/api/panel/identity-providers/{provider.id}",
        json={
            "name": provider.name,
            "provider_type": "oidc",
            "group_role_mappings": {"external-admins": ["missing-role"]},
        },
        headers=headers,
    )
    assert invalid.status_code == 400, invalid.text
    assert "unknown role" in invalid.text.lower()


@pytest.mark.asyncio
async def test_admin_panel_identity_provider_mapping_denies_without_permission(client, db):
    db.add(IdentityProvider(name="Denied OIDC", provider_type="oidc", is_active=True))
    await create_user(
        db,
        payload={
            "username": "identity_denied",
            "email": "identity-denied@example.com",
            "password": "password123",
            "roles": ["viewer"],
        },
    )
    await db.commit()
    headers = await _auth_headers_for(client, "identity_denied")

    response = await client.get("/admin/chat/api/panel/identity-providers", headers=headers)
    assert response.status_code == 403, response.text
    assert "identity_providers:read" in response.text


@pytest.mark.asyncio
async def test_admin_identity_group_create_assign_and_delete_guard(db):
    group = await create_group(
        db,
        payload={
            "name": "Release Team",
            "description": "Release operators",
            "rls_attributes": [{"key": "tenantid", "value": "11"}, {"key": "region", "value": "eu"}],
        },
    )
    assert group["name"] == "release team"
    assert group["member_count"] == 0
    assert group["rls_attributes"] == [{"key": "tenantid", "value": "11"}, {"key": "region", "value": "eu"}]

    user = await create_user(
        db,
        payload={
            "username": "group_user",
            "email": "group-user@example.com",
            "password": "password123",
            "roles": ["viewer"],
        },
    )
    updated = await update_user(db, admin_id="admin", user_id=user["id"], payload={"group_ids": [group["id"]]})
    assert updated["groups"][0]["name"] == "release team"

    groups = await list_groups(db)
    assigned = next(item for item in groups if item["id"] == group["id"])
    assert assigned["member_count"] == 1

    with pytest.raises(Exception) as assigned_error:
        await delete_group(db, group_id=group["id"])
    assert "assigned" in str(assigned_error.value).lower()

    updated = await update_user(db, admin_id="admin", user_id=user["id"], payload={"group_ids": []})
    assert updated["groups"] == []

    deleted = await delete_group(db, group_id=group["id"])
    assert deleted == {"status": "deleted"}


@pytest.mark.asyncio
async def test_admin_identity_group_panel_api(client, auth_headers):
    created = await client.post(
        "/admin/chat/api/panel/identity-groups",
        json={
            "name": "QA Team",
            "description": "Quality reviewers",
            "rls_attributes": [{"key": "tenantid", "value": "11"}],
        },
        headers=auth_headers,
    )
    assert created.status_code == 200, created.text
    group = created.json()
    assert group["name"] == "qa team"

    listed = await client.get("/admin/chat/api/panel/identity-groups", headers=auth_headers)
    assert listed.status_code == 200, listed.text
    assert any(item["id"] == group["id"] for item in listed.json())

    updated = await client.put(
        f"/admin/chat/api/panel/identity-groups/{group['id']}",
        json={
            "description": "Updated QA reviewers",
            "is_active": False,
            "rls_attributes": [{"key": "tenantid", "value": "12"}, {"key": "cost_center", "value": "ops"}],
        },
        headers=auth_headers,
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["description"] == "Updated QA reviewers"
    assert updated.json()["is_active"] is False
    assert updated.json()["rls_attributes"] == [
        {"key": "tenantid", "value": "12"},
        {"key": "cost_center", "value": "ops"},
    ]

    invalid = await client.put(
        f"/admin/chat/api/panel/identity-groups/{group['id']}",
        json={"rls_attributes": [{"key": "tenant-id", "value": "12"}]},
        headers=auth_headers,
    )
    assert invalid.status_code == 400, invalid.text

    deleted = await client.delete(f"/admin/chat/api/panel/identity-groups/{group['id']}", headers=auth_headers)
    assert deleted.status_code == 200, deleted.text
