"""LDAP connector tools (search, groups, membership, sync, provisioning) and their native connection test."""

# ruff: noqa: F401,I001,E501

import asyncio
import uuid
from pathlib import Path
import pytest
from sqlalchemy import select
from app.models import Session, User
from app.services.connector_test_service import run_connector_connection_test
from app.tools.registry import execute_tool
from app.tools.context import ToolContext


def _write_fake_ldap_binary(tmp_path: Path) -> Path:
    script = tmp_path / "ldapsearch"
    script.write_text(
        """#!/usr/bin/env python3
import sys

args = sys.argv[1:]
if '-VVV' in args:
    sys.stdout.write('ldapsearch 2.6.7\\n')
    sys.exit(0)

query = ' '.join(args)
user_alice = '''
dn: uid=ldap-phase34-alice,ou=Users,dc=example,dc=com
uid: ldap-phase34-alice
mail: ldap-phase34-alice@example.com
cn: Alice LDAP
displayName: Alice LDAP
memberOf: cn=engineering,ou=Groups,dc=example,dc=com
memberOf: cn=admins,ou=Groups,dc=example,dc=com
'''.strip()
user_bob = '''
dn: uid=ldap-phase34-bob,ou=Users,dc=example,dc=com
uid: ldap-phase34-bob
mail: ldap-phase34-bob@example.com
cn: Bob LDAP
displayName: Bob LDAP
memberOf: cn=engineering,ou=Groups,dc=example,dc=com
'''.strip()
group_engineering = '''
dn: cn=engineering,ou=Groups,dc=example,dc=com
cn: engineering
memberUid: ldap-phase34-alice
memberUid: ldap-phase34-bob
'''.strip()
group_admins = '''
dn: cn=admins,ou=Groups,dc=example,dc=com
cn: admins
memberUid: ldap-phase34-alice
'''.strip()

if 'objectClass=group' in query:
    if 'ldap-phase34-alice' in query:
        sys.stdout.write(group_engineering + '\\n\\n' + group_admins + '\\n')
    elif 'ldap-phase34-bob' in query:
        sys.stdout.write(group_engineering + '\\n')
    else:
        sys.stdout.write(group_engineering + '\\n\\n' + group_admins + '\\n')
    sys.exit(0)

if 'ldap-phase34-bob' in query:
    sys.stdout.write(user_bob + '\\n')
    sys.exit(0)
if 'ldap-phase34-alice' in query or 'phase34' in query or 'objectClass=person' in query or 'objectClass=user' in query:
    sys.stdout.write(user_alice + '\\n\\n' + user_bob + '\\n')
    sys.exit(0)

sys.stdout.write('')
sys.exit(0)
""",
        encoding="utf-8",
    )
    script.chmod(0o755)
    return script


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_ldap_tools_cover_search_groups_membership_sync_and_provisioning(db, tmp_path, auth_user):
    session = Session(
        id=str(uuid.uuid4()),
        user_id=auth_user.id,
        project_id=None,
        agent_type="diagnosis",
        status="active",
        metadata_={},
    )
    db.add(session)
    await db.commit()

    binary = _write_fake_ldap_binary(tmp_path)
    context = ToolContext(
        user_id=auth_user.id,
        project_ids=[],
        roles=["admin"],
        session_id=session.id,
        project_config={
            "tool_policy": {"high_risk_grants": ["sync_users", "user_provisioning"]},
            "ldap_server_url": "ldap://directory.example.com:389",
            "ldap_bind_dn": "cn=svc-octryx,dc=example,dc=com",
            "ldap_bind_password": "secret",
            "ldap_base_dn": "dc=example,dc=com",
            "ldap_user_base_dn": "ou=Users,dc=example,dc=com",
            "ldap_group_base_dn": "ou=Groups,dc=example,dc=com",
            "ldapsearch_binary": str(binary),
            "ldap_uid_attribute": "uid",
            "ldap_email_attribute": "mail",
            "ldap_display_name_attribute": "displayName",
            "ldap_group_name_attribute": "cn",
            "ldap_membership_attribute": "memberUid",
            "ldap_mode": "ldap",
        },
        capability_type="diagnosis",
        agent_mode_key="diagnosis",
        workspace_root=str(tmp_path),
        db=db,
    )

    users = await execute_tool("search_user", {"query": "phase34"}, context)
    assert users["count"] == 2

    groups = await execute_tool("get_groups", {"username": "ldap-phase34-alice"}, context)
    assert {item["name"] for item in groups["groups"]} == {"engineering", "admins"}

    membership = await execute_tool(
        "check_membership",
        {"username": "ldap-phase34-alice", "group_name": "admins"},
        context,
    )
    assert membership["is_member"] is True

    synced = await execute_tool(
        "sync_users",
        {"query": "phase34", "persist_local_users": True, "roles": ["viewer"]},
        context,
    )
    assert synced["created_count"] >= 2
    synced_user = (await db.execute(select(User).where(User.username == "ldap-phase34-alice"))).scalar_one()
    assert synced_user.auth_source == "ldap"

    provisioned = await execute_tool(
        "user_provisioning",
        {"username": "ldap-phase34-bob", "roles": ["viewer"]},
        context,
    )
    assert provisioned["status"] == "provisioned"
    local_bob = (await db.execute(select(User).where(User.username == "ldap-phase34-bob"))).scalar_one()
    assert local_bob.auth_source == "ldap"


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_ldap_connector_health_supports_native_connection_test(tmp_path):
    binary = _write_fake_ldap_binary(tmp_path)
    result = await run_connector_connection_test(
        "ldap",
        {
            "ldap_server_url": "ldap://directory.example.com:389",
            "ldap_base_dn": "dc=example,dc=com",
            "ldapsearch_binary": str(binary),
        },
    )
    assert result["ok"] is True
    assert result["summary"] == "LDAP client probe succeeded."
    assert "directory.example.com" not in str(result)
